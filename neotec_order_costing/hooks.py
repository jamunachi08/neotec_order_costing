app_name = "neotec_order_costing"
app_title = "Neotec Order Costing"
app_publisher = "Neotec Integrated Solution"
app_description = "Order-wise COGS pegging, brand-wise procurement split, configurable batch naming and profitability reporting"
app_email = "support@neotec.ai"
app_license = "Commercial"
required_apps = ["erpnext"]

# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
app_include_js = "/assets/neotec_order_costing/js/neotec_order_costing.bundle.js"

doctype_js = {
    "Item": "public/js/item.js",
    "Supplier Quotation": "public/js/supplier_quotation.js",
    "Sales Order": "public/js/sales_order.js",
    "Delivery Note": "public/js/delivery_note.js",
    "Purchase Order": "public/js/purchase_order.js",
    "Sales Invoice": "public/js/sales_invoice.js",
    "Material Request": "public/js/material_request.js",
}

# ---------------------------------------------------------------------------
# Install / migrate
# ---------------------------------------------------------------------------
after_install = "neotec_order_costing.install.after_install"
after_migrate = "neotec_order_costing.install.after_migrate"

# ---------------------------------------------------------------------------
# Document events
#
# Stock inward is handled from BOTH Purchase Receipt and Purchase Invoice so
# that clients who skip the PR entirely (direct PI with Update Stock) get the
# same pegging and batch behaviour.
# ---------------------------------------------------------------------------
doc_events = {
    "Sales Order": {
        "before_validate": [
            "neotec_order_costing.api.parts.stamp_part_numbers",
            "neotec_order_costing.api.cost_stamp.stamp_costs",
        ],
        "on_submit": "neotec_order_costing.api.peg.on_sales_order_submit",
        "on_cancel": "neotec_order_costing.api.peg.on_sales_order_cancel",
    },
    "Material Request": {
        "validate": "neotec_order_costing.api.brand_split.validate_split_grouping",
    },
    "Supplier Quotation": {
        "on_submit": "neotec_order_costing.api.consolidation.capture_quoted_rates",
    },
    "Purchase Order": {
        "before_validate": "neotec_order_costing.api.parts.stamp_part_numbers",
        "validate": "neotec_order_costing.api.brand_split.validate_split_grouping",
        "on_submit": [
            "neotec_order_costing.api.peg.on_purchase_order_submit",
            "neotec_order_costing.api.cost_stamp.on_purchase_rate_change",
        ],
        "on_cancel": "neotec_order_costing.api.peg.on_purchase_order_cancel",
    },
    "Purchase Receipt": {
        "before_validate": [
            "neotec_order_costing.api.equivalence.check_substitutions",
            "neotec_order_costing.api.batching.apply_auto_batch",
        ],
        "on_submit": [
            "neotec_order_costing.api.peg.on_stock_inward",
            "neotec_order_costing.api.equivalence.record_substitutions",
        ],
        "on_cancel": "neotec_order_costing.api.peg.on_stock_inward_cancel",
    },
    "Purchase Invoice": {
        "before_validate": [
            "neotec_order_costing.api.equivalence.check_substitutions",
            "neotec_order_costing.api.batching.apply_auto_batch",
        ],
        "on_submit": [
            "neotec_order_costing.api.peg.on_stock_inward",
            "neotec_order_costing.api.equivalence.record_substitutions",
        ],
        "on_cancel": "neotec_order_costing.api.peg.on_stock_inward_cancel",
    },
    "Landed Cost Voucher": {
        "on_submit": "neotec_order_costing.api.peg.refresh_landed_rates",
    },
    "Delivery Note": {
        "before_validate": [
            "neotec_order_costing.api.delivery.apply_pegged_batches",
            "neotec_order_costing.api.parts.stamp_part_numbers",
            "neotec_order_costing.api.cost_stamp.stamp_costs",
        ],
        "on_submit": [
            "neotec_order_costing.api.delivery.consume_peg",
            "neotec_order_costing.api.as_built.build_configurations",
        ],
        "on_cancel": [
            "neotec_order_costing.api.delivery.release_peg",
            "neotec_order_costing.api.as_built.delete_configurations",
        ],
    },
    "Sales Invoice": {
        "before_validate": [
            "neotec_order_costing.api.delivery.apply_pegged_batches",
            "neotec_order_costing.api.parts.stamp_part_numbers",
            "neotec_order_costing.api.cost_stamp.stamp_costs",
        ],
        "on_submit": [
            "neotec_order_costing.api.delivery.consume_peg",
            "neotec_order_costing.api.as_built.build_configurations",
        ],
        "on_cancel": [
            "neotec_order_costing.api.delivery.release_peg",
            "neotec_order_costing.api.as_built.delete_configurations",
        ],
    },
    "Quotation": {
        "before_validate": [
            "neotec_order_costing.api.parts.stamp_part_numbers",
            "neotec_order_costing.api.cost_stamp.stamp_costs",
        ],
    },
    "Item": {
        "validate": "neotec_order_costing.api.specs.apply_template",
    },
}

# ---------------------------------------------------------------------------
# Creation tab / connections
# ---------------------------------------------------------------------------
override_doctype_dashboards = {
    "Sales Order": "neotec_order_costing.api.dashboards.sales_order_dashboard",
    "Item": "neotec_order_costing.api.dashboards.item_dashboard",
    "Purchase Order": "neotec_order_costing.api.dashboards.purchase_order_dashboard",
    "Batch": "neotec_order_costing.api.dashboards.batch_dashboard",
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [["name", "like", "%-custom_noc_%"]],
    }
]
