from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class StockTransferRequestShipWizard(models.TransientModel):
    _name = 'ff.stock.transfer.ship.wizard'
    _description = 'Prepare Stock Transfer Request Shipment'

    request_id = fields.Many2one('ff.stock.transfer.request', string='Request', required=True, readonly=True)
    line_ids = fields.One2many('ff.stock.transfer.ship.wizard.line', 'wizard_id', string='Line')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        request = self.env['ff.stock.transfer.request'].browse(self.env.context.get('default_request_id')).exists()
        if request:
            values['request_id'] = request.id
            shipped = request._done_qty_by_product('ship')
            values['line_ids'] = [(0, 0, {
                'product_id': line.product_id.id,
                'uom_id': line.product_id.uom_id.id,
                'quantity': max(line.product_id.uom_id._compute_quantity(line.requested_qty, line.product_id.uom_id) - shipped.get(line.product_id.id, 0.0), 0.0),
            }) for line in request.line_ids]
        return values

    def action_ship(self):
        self.ensure_one()
        quantities = {line.product_id: line.quantity for line in self.line_ids if line.product_id and line.quantity > 0}
        if not quantities:
            # Odoo 20 may not flush unchanged default values from an editable
            # one2many before a transient button RPC. Rebuild the suggested
            # outstanding quantities so the default Ship action remains safe.
            request = self.request_id
            shipped = request._done_qty_by_product('ship')
            quantities = {
                line.product_id: max(
                    line.product_id.uom_id._compute_quantity(line.requested_qty, line.product_id.uom_id)
                    - shipped.get(line.product_id.id, 0.0), 0.0,
                )
                for line in request.line_ids
            }
            quantities = {product: qty for product, qty in quantities.items() if qty > 0}
        if not quantities:
            raise ValidationError(_('Enter at least one positive shipment quantity.'))
        self.request_id._ship_quantities(quantities)
        return {'type': 'ir.actions.act_window_close'}


class StockTransferRequestShipWizardLine(models.TransientModel):
    _name = 'ff.stock.transfer.ship.wizard.line'
    _description = 'Shipment Quantity'

    wizard_id = fields.Many2one('ff.stock.transfer.ship.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True, readonly=True)
    uom_id = fields.Many2one('uom.uom', string='UoM', required=True, readonly=True)
    quantity = fields.Float('Quantity to Ship', required=True, digits='Product Unit')


class StockTransferRequestReceiveWizard(models.TransientModel):
    _name = 'ff.stock.transfer.receive.wizard'
    _description = 'Confirm Stock Transfer Request Receipt'

    request_id = fields.Many2one('ff.stock.transfer.request', string='Request', required=True, readonly=True)
    line_ids = fields.One2many('ff.stock.transfer.receive.wizard.line', 'wizard_id', string='Line')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        request = self.env['ff.stock.transfer.request'].browse(self.env.context.get('default_request_id')).exists()
        if request:
            values['request_id'] = request.id
            shipped, received = request._done_qty_by_product('ship'), request._done_qty_by_product('receive')
            values['line_ids'] = [(0, 0, {
                'product_id': line.product_id.id,
                'uom_id': line.product_id.uom_id.id,
                'quantity': max(shipped.get(line.product_id.id, 0.0) - received.get(line.product_id.id, 0.0), 0.0),
            }) for line in request.line_ids]
        return values

    def action_receive(self):
        self.ensure_one()
        quantities = {line.product_id: line.quantity for line in self.line_ids if line.product_id and line.quantity > 0}
        if not quantities:
            request = self.request_id
            shipped, received = request._done_qty_by_product('ship'), request._done_qty_by_product('receive')
            quantities = {
                line.product_id: max(shipped.get(line.product_id.id, 0.0) - received.get(line.product_id.id, 0.0), 0.0)
                for line in request.line_ids
            }
            quantities = {product: qty for product, qty in quantities.items() if qty > 0}
        if not quantities:
            raise ValidationError(_('Enter at least one positive receipt quantity.'))
        self.request_id._receive_quantities(quantities)
        return {'type': 'ir.actions.act_window_close'}


class StockTransferRequestReceiveWizardLine(models.TransientModel):
    _name = 'ff.stock.transfer.receive.wizard.line'
    _description = 'Receipt Quantity'

    wizard_id = fields.Many2one('ff.stock.transfer.receive.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True, readonly=True)
    uom_id = fields.Many2one('uom.uom', string='UoM', required=True, readonly=True)
    quantity = fields.Float('Quantity Received', required=True, digits='Product Unit')
