# FF Stock Transfer Request

`ff_stock_transfer_request` adds a controlled branch replenishment request workflow to Odoo 20 Community.

The addon is deliberately a workflow layer over native `stock.picking`, `stock.move`, reservations, validation, transit locations and traceability. It does not write `stock.quant` or fabricate inventory/accounting entries.

## Setup

1. Install the addon with Inventory and Sales/Inventory installed (the latter provides `res.users.property_warehouse_id`).
2. Configure Inventory settings → Stock Transfer Requests → Main Source Warehouse.
3. Set each user's standard Default Warehouse. This is used for destination authorization and source-warehouse officer authorization.
4. Configure inter-warehouse routes/transit in standard Inventory configuration when route automation is required. The addon uses the company internal transit location by default.
5. Assign the addon groups: Request User, Warehouse Officer, Receiving User and Warehouse Manager.

## Workflow

Requesters submit products and quantities. Officers enter actual shipment quantities in the request wizard; Odoo reserves and validates a native shipment to transit. Receivers enter actual quantities and Odoo validates a native receipt from transit. Repeated batches remain linked to the original request, and all operational totals are computed from done stock moves.

Tracked products that require lot/serial details are intentionally left to Odoo's native picking validation. Open the linked picking from the request, complete tracking details, and validate it there.

## Security

Warehouse access is checked server-side on every workflow method. Record rules provide company isolation and warehouse-scoped visibility, but they are not the only authorization boundary.

## Features

- Request products and quantities from an authorized destination warehouse.
- Submit, ship, receive, and complete requests with a clear status bar.
- Create native shipment and receipt pickings from guided wizards.
- Record actual shipped and received quantities, not only requested quantities.
- Show every linked shipment, receipt, and return in the Stock Operations smart tab.
- Calculate net received quantities after completed returns.
- Reorder a completed request manually or automatically through the daily replenishment cron.
- Keep module roles independent from standard Inventory user/manager roles.
- Apply company and warehouse checks on the server for every workflow action.
- Include Arabic translations for workflow labels, security groups, menus, statuses, and fields.

## Workflow

1. A branch requester creates a request and adds products with requested quantities.
2. The request is submitted for warehouse processing.
3. A warehouse officer prepares the shipment and enters actual quantities to ship.
4. Odoo reserves and validates a native shipment from the source warehouse to transit.
5. A receiving user confirms the actual quantity received at the destination warehouse.
6. Odoo validates the native receipt and updates request totals and status.
7. Any return picking remains linked to the request and reduces net received quantity.

The **Reorder** action creates a new draft request with the remaining product lines. The scheduled replenishment job only creates draft requests for review; it never ships stock silently.

## Installation

1. Install Odoo 20 Community with `stock`, `sale_stock`, and `mail` available.
2. Copy `ff_stock_transfer_request` to an addons path and update the Apps list.
3. Install **Stock Transfer Requests** from Apps.
4. Open Inventory settings and configure the main source warehouse.
5. Set each user's standard Default Warehouse. This determines destination authorization and source-warehouse responsibility.
6. Assign one or more module roles under Users → Access Rights:
   - Transfer Request User
   - Transfer Request Warehouse Officer
   - Transfer Request Receiving User
   - Transfer Request Warehouse Manager

The module roles are intentionally separate from standard Inventory roles. Users can work on authorized requests without unrestricted access to Inventory menus or arbitrary stock operations.

## Configuration notes

- Configure the standard Odoo transit location and routes when your warehouse flow requires them.
- Products requiring lots or serial numbers must be completed using Odoo's native tracking controls on the linked picking.
- Multi-company and warehouse restrictions are enforced server-side; test the assigned warehouse on each role before go-live.

## Compatibility

- Odoo: 20.0 Community
- License: LGPL-3
- Dependencies: `stock`, `sale_stock`, `mail`
- Maintainer: Flous Flow — https://flousflow.com

## Known boundaries

- Physical barcode scanners, carrier integrations, and automated route strategies are provided by standard Odoo or separate addons.
- The automatic reorder job creates drafts only and requires warehouse approval.
- Apps Store review, external hosting, and production-load testing must be completed for the target deployment separately.
