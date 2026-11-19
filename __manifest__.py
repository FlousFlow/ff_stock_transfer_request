{
    'name': 'Stock Transfer Requests',
    'version': '20.0.1.0.3',
    'category': 'Inventory/Inventory',
    'summary': 'Controlled branch replenishment requests using native stock operations',
    'description': """
Stock Transfer Requests
=======================
Controlled inter-warehouse replenishment workflow for Odoo 20 Community.

Create requests, prepare native shipments, confirm actual receipts, trace
returns, calculate net quantities, and create safe draft reorders without
granting unrestricted Inventory access. Arabic translations and dedicated
warehouse roles are included.
    """,
    'author': 'Flous Flow',
    'website': 'https://flousflow.com',
    'maintainers': ['Flous Flow'],
    'license': 'LGPL-3',
    'depends': ['stock', 'sale_stock', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/sequence.xml',
        'data/ir_cron.xml',
        'views/stock_transfer_request_views.xml',
        'views/stock_transfer_request_wizard_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'demo': [],
    'images': ['static/description/banner.jpg'],
    'installable': True,
    'application': True,
}
