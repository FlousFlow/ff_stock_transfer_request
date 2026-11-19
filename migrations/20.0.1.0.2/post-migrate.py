from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    pickings = env['stock.picking'].search([
        ('transfer_request_id', '=', False),
        ('return_id.transfer_request_id', '!=', False),
    ])
    for picking in pickings:
        picking.write({
            'transfer_request_id': picking.return_id.transfer_request_id.id,
            'transfer_request_stage': 'return',
        })
