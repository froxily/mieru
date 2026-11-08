ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "order_id": (
        "order_id", "orderid", "order_no", "order_number", "ordernumber", "order_num", "order_ref", "order_reference",
        "invoice", "invoice_no", "invoiceno", "invoice_number", "invoice_id", "receipt_no", "receipt_number", "receipt_id",
        "bill_no", "sales_order", "so_number", "basket_id", "cart_id",
        "注文番号", "注文id", "受注番号", "伝票番号", "請求書番号", "オーダー番号",
        "pedido", "id_pedido", "numero_pedido", "num_pedido", "factura", "numero_factura",
    ),
    "line_id": (
        "line_id", "line_item_id", "order_item_id", "order_line_id", "line_number", "line_no", "item_line",
        "transaction_id", "txn_id", "transaction_no", "row_id", "record_id", "明細番号", "明細id", "取引id", "取引番号",
        "id_transacao", "id_transaccion",
    ),
    "order_date": (
        "order_date", "date", "invoice_date", "invoicedate", "purchase_date", "order_purchase_timestamp", "created_at",
        "transaction_date", "sale_date", "sales_date", "order_datetime", "order_time", "timestamp", "datetime", "day",
        "purchase_timestamp", "date_of_sale", "orderdate", "txn_date",
        "注文日", "注文日時", "受注日", "日付", "売上日", "購入日", "取引日", "販売日",
        "data", "data_pedido", "data_compra", "fecha", "fecha_pedido", "fecha_venta",
    ),
    "customer_id": (
        "customer_id", "customerid", "customer", "customer_no", "customer_number", "customer_code", "client_id", "client",
        "buyer_id", "buyer", "user_id", "member_id", "account_id", "customer_unique_id", "shopper_id",
        "顧客id", "顧客番号", "顧客コード", "会員id", "会員番号", "顧客",
        "cliente", "id_cliente", "codigo_cliente",
    ),
    "product_id": (
        "product_id", "productid", "sku", "item_code", "stockcode", "stock_code", "product_code", "item_id", "asin", "upc",
        "ean", "article_number", "part_number", "商品コード", "商品id", "品番", "商品番号", "jan", "jancode",
        "id_produto", "codigo_produto", "id_producto", "codigo_producto",
    ),
    "product_name": (
        "product_name", "product", "item", "item_name", "description", "product_description", "item_description",
        "product_title", "title", "goods", "商品名", "品名", "商品", "製品名",
        "produto", "nome_produto", "producto", "nombre_producto",
    ),
    "category": (
        "category", "product_category", "category_name", "product_category_name", "department", "product_type",
        "product_line", "item_category", "main_category", "sub_category", "subcategory", "genre",
        "カテゴリ", "カテゴリー", "分類", "商品カテゴリ", "ジャンル", "部門",
        "categoria", "categoria_produto",
    ),
    "quantity": (
        "quantity", "qty", "units", "unit_count", "quantity_ordered", "qty_ordered", "units_sold", "quantity_sold", "pieces",
        "数量", "個数", "販売数", "販売数量", "点数",
        "quantidade", "qtd", "cantidad",
    ),
    "unit_price": (
        "unit_price", "price", "unitprice", "price_each", "selling_price", "sale_price", "item_price", "list_price", "price_per_unit",
        "単価", "価格", "販売価格", "売価",
        "preco", "preco_unitario", "precio", "precio_unitario",
    ),
    "amount": (
        "amount", "sales", "revenue", "total", "line_total", "sales_amount", "total_amount", "gross_sales", "net_sales",
        "subtotal", "sub_total", "line_amount", "extended_price", "total_price", "sale_amount", "turnover", "value",
        "売上", "売上金額", "売上高", "金額", "合計", "小計", "合計金額", "販売金額",
        "valor", "valor_total", "importe", "total_venta",
    ),
    "order_total": (
        "order_total", "order_amount", "grand_total", "total_paid", "order_value", "invoice_total", "invoice_amount",
        "注文合計", "請求金額", "総額",
    ),
    "discount": (
        "discount", "discount_amount", "discounts", "promo", "promotion", "coupon", "coupon_amount", "markdown",
        "割引", "値引", "値引き", "割引額", "クーポン",
        "desconto", "descuento",
    ),
    "tax": ("tax", "vat", "sales_tax", "tax_amount", "gst", "税", "消費税", "税額", "imposto", "impuesto", "iva"),
    "shipping": (
        "shipping", "shipping_cost", "shipping_fee", "freight", "freight_value", "delivery_fee", "delivery_cost", "postage",
        "送料", "配送料", "frete", "envio",
    ),
    "unit_cost": ("unit_cost", "cost_price", "purchase_price", "cost_per_unit", "原価", "仕入単価", "原単価", "custo_unitario", "costo_unitario"),
    "line_cost": ("cost", "cogs", "total_cost", "cost_of_goods", "line_cost", "原価合計", "仕入原価", "custo", "costo"),
    "refund_amount": ("refund", "refund_amount", "refunded_amount", "returned_amount", "返金", "返金額", "返品金額", "reembolso"),
    "status": (
        "status", "order_status", "state_of_order", "fulfillment_status", "payment_status", "transaction_status",
        "状態", "ステータス", "注文状態", "situacao", "estado_pedido",
    ),
    "return_flag": ("returned", "is_return", "return", "return_flag", "is_returned", "返品", "返品フラグ", "devolvido"),
    "channel": (
        "channel", "sales_channel", "source", "platform", "marketplace", "store", "shop", "store_name", "medium",
        "チャネル", "チャネル名", "販売チャネル", "店舗", "店舗名", "canal",
    ),
    "region": (
        "region", "state", "province", "prefecture", "customer_state", "ship_state", "billing_state", "territory", "area",
        "都道府県", "地域", "エリア", "県", "estado", "uf", "provincia",
    ),
    "country": ("country", "country_code", "ship_country", "billing_country", "nation", "国", "国名", "pais"),
    "city": ("city", "town", "customer_city", "ship_city", "市区町村", "市", "都市", "cidade", "ciudad"),
    "currency": ("currency", "currency_code", "curr", "通貨", "moeda", "moneda"),
    "payment_method": ("payment_method", "payment_type", "payment", "tender", "支払方法", "決済方法", "forma_pagamento", "metodo_pago"),
}

ROLE_LABELS: dict[str, str] = {
    "order_id": "Order ID",
    "line_id": "Line / transaction ID",
    "order_date": "Order date",
    "customer_id": "Customer ID",
    "product_id": "Product ID / SKU",
    "product_name": "Product name",
    "category": "Category",
    "quantity": "Quantity",
    "unit_price": "Unit price",
    "amount": "Sales amount",
    "line_amount": "Line amount",
    "order_total": "Order total",
    "discount": "Discount",
    "tax": "Tax",
    "shipping": "Shipping / freight",
    "unit_cost": "Unit cost",
    "line_cost": "Line cost",
    "refund_amount": "Refund amount",
    "status": "Order status",
    "return_flag": "Return flag",
    "channel": "Sales channel",
    "region": "Region / state",
    "country": "Country",
    "city": "City",
    "currency": "Currency",
    "payment_method": "Payment method",
}

ROLE_KINDS: dict[str, str] = {
    "order_id": "identifier",
    "line_id": "identifier",
    "customer_id": "identifier",
    "product_id": "identifier",
    "order_date": "date",
    "product_name": "text",
    "category": "category",
    "status": "category",
    "channel": "category",
    "region": "category",
    "country": "category",
    "city": "category",
    "currency": "category",
    "payment_method": "category",
    "return_flag": "boolean",
    "quantity": "quantity",
    "unit_price": "money",
    "amount": "money",
    "order_total": "money",
    "discount": "money",
    "tax": "money",
    "shipping": "money",
    "unit_cost": "money",
    "line_cost": "money",
    "refund_amount": "money",
}

FINANCIAL_ROLES: frozenset[str] = frozenset(role for role, kind in ROLE_KINDS.items() if kind == "money")

STATUS_TOKENS: dict[str, tuple[str, ...]] = {
    "cancelled": ("cancel", "canceled", "cancelled", "void", "voided", "キャンセル", "取消", "取り消し", "cancelado", "cancelada", "anulado", "anulada"),
    "returned": ("return", "returned", "refund", "refunded", "返品", "返金", "devolvido", "devolvida", "devuelto", "reembolsado"),
    "completed": (
        "complete", "completed", "delivered", "shipped", "paid", "fulfilled", "closed", "success", "successful", "done",
        "完了", "配送済", "出荷済", "発送済", "支払済", "entregue", "concluido", "pagado", "entregado",
    ),
    "pending": ("pending", "processing", "created", "approved", "invoiced", "unpaid", "open", "new", "保留", "処理中", "未発送", "pendente", "pendiente"),
}

TRUE_TOKENS: frozenset[str] = frozenset({"true", "yes", "y", "1", "t", "はい", "sim", "si", "returned"})
