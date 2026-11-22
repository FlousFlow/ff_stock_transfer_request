from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ff_main_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Main Source Warehouse',
        company_dependent=True,
        domain="[('company_id', '=', company_id)]",
        help='Default source warehouse for stock transfer requests in this company.',
    )
    ff_transit_location_id = fields.Many2one(
        'stock.location',
        string='Transfer Transit Location',
        company_dependent=True,
        domain="[('usage', '=', 'transit'), '|', ('company_id', '=', company_id), ('company_id', '=', False)]",
        help='Optional transit location. If empty, the company internal transit location is used.',
    )

    def set_values(self):
        super().set_values()
        self.env['ir.config_parameter'].sudo().set_int(
            'ff_stock_transfer_request.main_warehouse_id',
            self.ff_main_warehouse_id.id or False,
        )
        self.env['ir.config_parameter'].sudo().set_int(
            'ff_stock_transfer_request.transit_location_id',
            self.ff_transit_location_id.id or False,
        )

    def get_values(self):
        values = super().get_values()
        params = self.env['ir.config_parameter'].sudo()
        values.update(
            ff_main_warehouse_id=params.get_int('ff_stock_transfer_request.main_warehouse_id'),
            ff_transit_location_id=params.get_int('ff_stock_transfer_request.transit_location_id'),
        )
        return values
