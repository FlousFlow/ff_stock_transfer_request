from collections import defaultdict

from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    transfer_request_id = fields.Many2one(
        'ff.stock.transfer.request', string='Transfer Request', copy=False,
        index=True, ondelete='set null', check_company=True,
    )
    transfer_request_stage = fields.Selection(
        [('ship', 'Shipment'), ('receive', 'Receipt'), ('return', 'Return')],
        string='Request Operation', copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        for picking in pickings:
            picking._link_return_to_transfer_request()
        return pickings

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('skip_return_request_link') and ('return_id' in vals or 'transfer_request_id' in vals):
            self._link_return_to_transfer_request()
        return result

    def _link_return_to_transfer_request(self):
        for picking in self.filtered(lambda p: p.return_id.transfer_request_id and not p.transfer_request_id):
            picking.with_context(skip_return_request_link=True).write({
                'transfer_request_id': picking.return_id.transfer_request_id.id,
                'transfer_request_stage': 'return',
            })
        return True

    def button_validate(self):
        result = super().button_validate()
        if result is True:
            requests = self.filtered('transfer_request_id').mapped('transfer_request_id')
            if requests:
                requests._refresh_state()
        return result


class StockTransferRequest(models.Model):
    _name = 'ff.stock.transfer.request'
    _description = 'Stock Transfer Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'
    _check_company_auto = True

    name = fields.Char('Request Reference', default='New', copy=False, readonly=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company, tracking=True)
    user_id = fields.Many2one('res.users', string='Requesting User', required=True,
                              default=lambda self: self.env.user, readonly=True, tracking=True)
    source_warehouse_id = fields.Many2one('stock.warehouse', string='Source Warehouse', required=True,
                                          default=lambda self: self._default_source_warehouse(),
                                          readonly=True, tracking=True, check_company=True)
    destination_warehouse_id = fields.Many2one('stock.warehouse', string='Destination Warehouse', required=True,
                                               default=lambda self: self._default_destination_warehouse(),
                                               tracking=True, check_company=True)
    request_date = fields.Datetime('Request Date', required=True, default=fields.Datetime.now, readonly=True)
    requested_delivery_date = fields.Date('Requested Delivery Date')
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Submitted'), ('partially_shipped', 'Partially Shipped'),
        ('awaiting_receipt', 'Shipped / Awaiting Receipt'), ('partially_received', 'Partially Received'),
        ('completed', 'Completed'), ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)
    line_ids = fields.One2many('ff.stock.transfer.request.line', 'request_id', string='Products', copy=True)
    picking_ids = fields.One2many('stock.picking', 'transfer_request_id', string='Stock Operations', readonly=True)
    outgoing_picking_ids = fields.One2many('stock.picking', 'transfer_request_id', domain=[('transfer_request_stage', '=', 'ship')],
                                           string='Shipments', readonly=True)
    incoming_picking_ids = fields.One2many('stock.picking', 'transfer_request_id', domain=[('transfer_request_stage', '=', 'receive')],
                                           string='Receipts', readonly=True)
    picking_count = fields.Integer(compute='_compute_picking_count')
    total_requested_qty = fields.Float(compute='_compute_totals', string='Requested Quantity')
    total_shipped_qty = fields.Float(compute='_compute_totals', string='Shipped Quantity')
    total_received_qty = fields.Float(compute='_compute_totals', string='Received Quantity')
    pending_ship_qty = fields.Float(compute='_compute_totals', string='Pending Shipment')
    pending_receipt_qty = fields.Float(compute='_compute_totals', string='Pending Receipt')
    has_discrepancy = fields.Boolean(compute='_compute_totals', string='Has Discrepancy')
    submitted_by = fields.Many2one('res.users', readonly=True, copy=False)
    submitted_at = fields.Datetime(readonly=True, copy=False)
    shipped_by = fields.Many2one('res.users', readonly=True, copy=False)
    shipped_at = fields.Datetime(readonly=True, copy=False)
    received_by = fields.Many2one('res.users', readonly=True, copy=False)
    received_at = fields.Datetime(readonly=True, copy=False)
    reorder_enabled = fields.Boolean(
        string='Automatic Reorder', default=False, copy=True,
        help='Create a new draft request automatically after the interval when this request is completed.',
    )
    reorder_interval_days = fields.Integer(
        string='Reorder Every (Days)', default=30, copy=True,
        help='Number of days between automatically generated reorder requests.',
    )
    next_reorder_date = fields.Date(string='Next Reorder Date', copy=True, readonly=True)
    reorder_parent_id = fields.Many2one(
        'ff.stock.transfer.request', string='Reordered From', copy=False, readonly=True,
        index=True, ondelete='set null',
    )
    reorder_child_ids = fields.One2many(
        'ff.stock.transfer.request', 'reorder_parent_id', string='Reorder Requests', readonly=True,
    )

    @api.model
    def _default_source_warehouse(self):
        configured = self.env['ir.config_parameter'].sudo().get_int('ff_stock_transfer_request.main_warehouse_id')
        warehouse = self.env['stock.warehouse'].browse(configured).exists() if configured else self.env['stock.warehouse']
        if warehouse and warehouse.company_id == self.env.company:
            return warehouse
        return self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], order='sequence,id', limit=1)

    @api.model
    def _default_destination_warehouse(self):
        warehouse = getattr(self.env.user, 'property_warehouse_id', self.env['stock.warehouse'])
        return warehouse if warehouse and warehouse.company_id == self.env.company else self.env['stock.warehouse']

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            vals.setdefault('name', sequence.next_by_code('ff.stock.transfer.request') or 'New')
            vals.setdefault('user_id', self.env.uid)
            vals.setdefault('company_id', self.env.company.id)
            vals.setdefault('source_warehouse_id', self._default_source_warehouse().id)
            vals.setdefault('destination_warehouse_id', self._default_destination_warehouse().id)
        records = super().create(vals_list)
        for record in records:
            if not record.destination_warehouse_id:
                raise UserError(_('Your user is not assigned a default warehouse. Configure Default Warehouse first.'))
            record._check_warehouse_access('destination')
        return records

    @api.depends('picking_ids')
    def _compute_picking_count(self):
        for record in self:
            record.picking_count = len(record.picking_ids)

    def _done_qty_by_product(self, stage):
        self.ensure_one()
        result = defaultdict(float)
        pickings = self.picking_ids.filtered(lambda p: p.transfer_request_stage == stage)
        for move in pickings.move_ids.filtered(lambda m: m.state == 'done'):
            result[move.product_id.id] += move.uom_id._compute_quantity(move.quantity, move.product_id.uom_id)
        if stage == 'receive':
            returned = self._done_qty_by_product('return')
            for product_id, quantity in returned.items():
                result[product_id] -= quantity
        return result

    @api.depends('line_ids.requested_qty', 'line_ids.product_id', 'picking_ids.state', 'picking_ids.move_ids.quantity',
                 'picking_ids.move_ids.state', 'picking_ids.move_ids.product_id')
    def _compute_totals(self):
        for record in self:
            shipped = record._done_qty_by_product('ship') if record.id else {}
            received = record._done_qty_by_product('receive') if record.id else {}
            requested = sum(record.line_ids.mapped('requested_qty'))
            shipped_total = received_total = 0.0
            discrepancy = False
            for line in record.line_ids:
                line.shipped_qty = shipped.get(line.product_id.id, 0.0)
                line.received_qty = max(received.get(line.product_id.id, 0.0), 0.0)
                shipped_total += line.shipped_qty
                received_total += line.received_qty
                discrepancy |= line.received_qty > line.shipped_qty or line.shipped_qty > line.requested_qty
            record.total_requested_qty = requested
            record.total_shipped_qty = shipped_total
            record.total_received_qty = received_total
            record.pending_ship_qty = max(requested - shipped_total, 0.0)
            record.pending_receipt_qty = max(shipped_total - received_total, 0.0)
            record.has_discrepancy = discrepancy or received_total < shipped_total and record.state in ('completed', 'cancelled')

    @api.constrains('source_warehouse_id', 'destination_warehouse_id', 'company_id')
    def _check_warehouses(self):
        for record in self:
            if record.source_warehouse_id == record.destination_warehouse_id:
                raise ValidationError(_('Source and destination warehouses must be different.'))
            if record.source_warehouse_id.company_id != record.company_id or record.destination_warehouse_id.company_id != record.company_id:
                raise ValidationError(_('Both warehouses must belong to the request company.'))

    def _is_manager(self):
        return self.env.user.has_group('ff_stock_transfer_request.group_transfer_request_manager')

    def _check_role(self, group_xmlid):
        if not (self._is_manager() or self.env.user.has_group(group_xmlid)):
            raise AccessError(_('You are not authorized to perform this request operation.'))

    def _check_warehouse_access(self, role):
        self.ensure_one()
        if self._is_manager():
            return True
        assigned = getattr(self.env.user, 'property_warehouse_id', self.env['stock.warehouse'])
        warehouse = self.destination_warehouse_id if role == 'destination' else self.source_warehouse_id
        if not assigned or assigned != warehouse:
            raise AccessError(_('You are not authorized to operate this warehouse.'))
        return True

    def _check_lines(self):
        self.ensure_one()
        if not self.line_ids:
            raise ValidationError(_('Add at least one product before submitting the request.'))
        for line in self.line_ids:
            if not line.product_id or not line.product_id.is_storable:
                raise ValidationError(_('Only storable products can be transferred.'))
            if line.product_id.active is False:
                raise ValidationError(_('Archived products cannot be requested.'))
            try:
                line.uom_id._compute_quantity(1.0, line.product_id.uom_id)
            except (UserError, ValueError):
                raise ValidationError(_('The unit of measure must be compatible with the product UoM.'))
            if line.requested_qty <= 0:
                raise ValidationError(_('Requested quantities must be positive.'))

    def action_submit(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            record._check_warehouse_access('destination')
            record._check_lines()
            if record.reorder_enabled and record.reorder_interval_days <= 0:
                raise ValidationError(_('The automatic reorder interval must be greater than zero.'))
            if not record.source_warehouse_id:
                raise UserError(_('Configure a main source warehouse in Inventory settings.'))
            record.write({'state': 'submitted', 'submitted_by': self.env.uid, 'submitted_at': fields.Datetime.now()})
            record.message_post(body=_('Request submitted for warehouse preparation.'), subtype_xmlid='mail.mt_note')
        return True

    def _transit_location(self):
        self.ensure_one()
        request = self.sudo()
        configured = self.env['ir.config_parameter'].sudo().get_int('ff_stock_transfer_request.transit_location_id')
        location = self.env['stock.location'].sudo().browse(configured).exists() if configured else request.company_id.internal_transit_location_id
        if not location or location.usage != 'transit' or location.company_id not in (request.company_id, self.env['res.company']):
            raise UserError(_('Configure a valid transit location before shipping requests.'))
        return location

    def _prepare_picking(self, stage, quantities):
        self.ensure_one()
        request = self.sudo()
        transit = request._transit_location()
        if stage == 'ship':
            picking_type = request.source_warehouse_id.out_type_id
            source, destination = request.source_warehouse_id.lot_stock_id, transit
        else:
            picking_type = request.destination_warehouse_id.in_type_id
            source, destination = transit, request.destination_warehouse_id.lot_stock_id
        if not picking_type:
            raise UserError(_('The selected warehouse does not have a configured operation type.'))
        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': picking_type.id,
            'location_id': source.id,
            'location_dest_id': destination.id,
            'origin': request.name,
            'transfer_request_id': request.id,
            'transfer_request_stage': stage,
            'user_id': self.env.uid,
            'move_ids': [Command.create({
                'product_id': product.id,
                'product_uom_qty': qty,
                'uom_id': product.uom_id.id,
                'location_id': source.id,
                'location_dest_id': destination.id,
                'company_id': request.company_id.id,
                'picking_type_id': picking_type.id,
                'origin': request.name,
                'procure_method': 'make_to_stock',
            }) for product, qty in quantities.items() if qty > 0],
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    def action_prepare_ship(self):
        self.ensure_one()
        self._check_role('ff_stock_transfer_request.group_transfer_request_officer')
        if self.state not in ('submitted', 'partially_shipped'):
            raise UserError(_('This request is not awaiting shipment.'))
        self._check_warehouse_access('source')
        return {
            'type': 'ir.actions.act_window', 'name': _('Prepare & Ship'),
            'res_model': 'ff.stock.transfer.ship.wizard', 'view_mode': 'form',
            'target': 'new', 'context': {'default_request_id': self.id},
        }

    def _validate_picking(self, picking):
        result = picking.sudo().button_validate()
        if result is not True:
            raise UserError(_('Odoo requires additional native stock information (for example lot or serial numbers). Open the linked picking and complete it there.'))

    def _ship_quantities(self, quantities):
        self.ensure_one()
        self._check_role('ff_stock_transfer_request.group_transfer_request_officer')
        self._check_warehouse_access('source')
        self._check_lines()
        shipped = self._done_qty_by_product('ship')
        for product, qty in quantities.items():
            line = self.line_ids.filtered(lambda l: l.product_id == product)[:1]
            outstanding = line.product_id.uom_id._compute_quantity(line.requested_qty, product.uom_id) - shipped.get(product.id, 0.0)
            if float_compare(qty, outstanding, precision_digits=6) > 0:
                raise ValidationError(_('Shipment quantity for %s exceeds the outstanding request quantity.', product.display_name))
        picking = self._prepare_picking('ship', quantities)
        self._validate_picking(picking)
        self.write({'shipped_by': self.env.uid, 'shipped_at': fields.Datetime.now()})
        self._refresh_state()
        self.message_post(body=_('Stock shipment %s was validated.', picking.name), subtype_xmlid='mail.mt_note')
        return picking

    def action_confirm_receipt(self):
        self.ensure_one()
        self._check_role('ff_stock_transfer_request.group_transfer_request_receiver')
        if self.state not in ('awaiting_receipt', 'partially_received'):
            raise UserError(_('There is no outstanding shipment to receive.'))
        self._check_warehouse_access('destination')
        return {
            'type': 'ir.actions.act_window', 'name': _('Confirm Receipt'),
            'res_model': 'ff.stock.transfer.receive.wizard', 'view_mode': 'form',
            'target': 'new', 'context': {'default_request_id': self.id},
        }

    def _receive_quantities(self, quantities):
        self.ensure_one()
        self._check_role('ff_stock_transfer_request.group_transfer_request_receiver')
        self._check_warehouse_access('destination')
        shipped, received = self._done_qty_by_product('ship'), self._done_qty_by_product('receive')
        for product, qty in quantities.items():
            outstanding = shipped.get(product.id, 0.0) - received.get(product.id, 0.0)
            if float_compare(qty, outstanding, precision_digits=6) > 0:
                raise ValidationError(_('Receipt quantity for %s exceeds the shipped quantity awaiting receipt.', product.display_name))
        picking = self._prepare_picking('receive', quantities)
        self._validate_picking(picking)
        self.write({'received_by': self.env.uid, 'received_at': fields.Datetime.now()})
        self._refresh_state()
        self.message_post(body=_('Stock receipt %s was validated.', picking.name), subtype_xmlid='mail.mt_note')
        return picking

    def _refresh_state(self):
        for record in self:
            record._compute_totals()
            if record.total_received_qty and float_compare(record.total_received_qty, record.total_requested_qty, precision_digits=6) >= 0:
                state = 'completed'
            elif record.total_received_qty:
                state = 'partially_received'
            elif record.total_shipped_qty and float_compare(record.total_shipped_qty, record.total_requested_qty, precision_digits=6) >= 0:
                state = 'awaiting_receipt'
            elif record.total_shipped_qty:
                state = 'partially_shipped'
            else:
                state = record.state
            record.state = state
            if state == 'completed' and record.reorder_enabled and not record.next_reorder_date:
                record.next_reorder_date = fields.Date.add(
                    fields.Date.context_today(record), days=record.reorder_interval_days or 30,
                )

    def action_cancel(self):
        for record in self:
            if not self._is_manager():
                raise AccessError(_('Only a warehouse manager can cancel a request.'))
            if record.picking_ids.filtered(lambda p: p.state == 'done'):
                raise UserError(_('A request with completed stock operations cannot be cancelled.'))
            record.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')).action_cancel()
            record.state = 'cancelled'
            record.message_post(body=_('Request cancelled by an authorized manager.'), subtype_xmlid='mail.mt_note')
        return True

    def _prepare_reorder_vals(self):
        self.ensure_one()
        return {
            'company_id': self.company_id.id,
            'user_id': self.user_id.id,
            'source_warehouse_id': self.source_warehouse_id.id,
            'destination_warehouse_id': self.destination_warehouse_id.id,
            'reorder_enabled': self.reorder_enabled,
            'reorder_interval_days': self.reorder_interval_days,
            'reorder_parent_id': self.id,
            'line_ids': [Command.create({
                'product_id': line.product_id.id,
                'uom_id': line.uom_id.id,
                'requested_qty': line.requested_qty,
            }) for line in self.line_ids],
        }

    def action_reorder(self):
        self.ensure_one()
        if self.state != 'completed':
            raise UserError(_('Only completed requests can be reordered.'))
        existing = self.search([
            ('reorder_parent_id', '=', self.id),
            ('state', 'not in', ('completed', 'cancelled')),
        ], limit=1)
        if existing:
            return existing.get_formview_action()
        request = self.create(self._prepare_reorder_vals())
        self.message_post(body=_('A reorder request %s was created.', request.name), subtype_xmlid='mail.mt_note')
        return request.get_formview_action()

    @api.model
    def _cron_create_automatic_reorders(self):
        today = fields.Date.context_today(self)
        requests = self.sudo().search([
            ('state', '=', 'completed'),
            ('reorder_enabled', '=', True),
            ('reorder_interval_days', '>', 0),
            '|', ('next_reorder_date', '=', False), ('next_reorder_date', '<=', today),
        ])
        for request in requests:
            if not request.next_reorder_date:
                request.write({'next_reorder_date': fields.Date.add(today, days=request.reorder_interval_days)})
                continue
            existing = self.search([
                ('reorder_parent_id', '=', request.id),
                ('state', 'not in', ('completed', 'cancelled')),
            ], limit=1)
            if not existing:
                child = self.create(request._prepare_reorder_vals())
                request.message_post(
                    body=_('Automatic reorder request %s was created.', child.name),
                    subtype_xmlid='mail.mt_note',
                )
            request.write({'next_reorder_date': fields.Date.add(today, days=request.reorder_interval_days)})
        return True

    def action_view_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Stock Operations'),
            'res_model': 'stock.picking', 'view_mode': 'list,form',
            'domain': [('transfer_request_id', '=', self.id)],
        }


class StockTransferRequestLine(models.Model):
    _name = 'ff.stock.transfer.request.line'
    _description = 'Stock Transfer Request Line'
    _check_company_auto = True

    request_id = fields.Many2one('ff.stock.transfer.request', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='request_id.company_id', store=True)
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain="[('is_storable', '=', True), ('active', '=', True)]")
    uom_id = fields.Many2one('uom.uom', string='Product UoM', required=True)
    requested_qty = fields.Float('Requested Quantity', required=True, digits='Product Unit')
    shipped_qty = fields.Float('Shipped Quantity', compute='_compute_quantities', store=False, digits='Product Unit')
    received_qty = fields.Float('Received Quantity', compute='_compute_quantities', store=False, digits='Product Unit')
    remaining_to_ship = fields.Float(compute='_compute_quantities', string='Remaining to Ship', digits='Product Unit')
    awaiting_receipt = fields.Float(compute='_compute_quantities', string='Awaiting Receipt', digits='Product Unit')
    has_discrepancy = fields.Boolean(compute='_compute_quantities')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            line.uom_id = line.product_id.uom_id

    @api.depends('requested_qty', 'product_id', 'request_id.picking_ids.state', 'request_id.picking_ids.move_ids.quantity',
                 'request_id.picking_ids.move_ids.state')
    def _compute_quantities(self):
        for line in self:
            shipped = received = 0.0
            if line.request_id.id and line.product_id:
                shipped = line.request_id._done_qty_by_product('ship').get(line.product_id.id, 0.0)
                received = line.request_id._done_qty_by_product('receive').get(line.product_id.id, 0.0)
            line.shipped_qty = shipped
            line.received_qty = received
            line.remaining_to_ship = max(line.product_id.uom_id._compute_quantity(line.requested_qty, line.product_id.uom_id) - shipped, 0.0) if line.product_id else 0.0
            line.awaiting_receipt = max(shipped - received, 0.0)
            line.has_discrepancy = received > shipped or shipped > (line.product_id.uom_id._compute_quantity(line.requested_qty, line.product_id.uom_id) if line.product_id else 0.0)

    @api.constrains('requested_qty', 'product_id', 'uom_id')
    def _check_line(self):
        for line in self:
            if line.requested_qty <= 0:
                raise ValidationError(_('Requested quantity must be positive.'))
            if line.product_id:
                try:
                    line.uom_id._compute_quantity(1.0, line.product_id.uom_id)
                except (UserError, ValueError):
                    raise ValidationError(_('The unit of measure must be compatible with the product UoM.'))
