import logging

# Создание таблицы specifications
CREATE_specifications_TABLE = """
    CREATE TABLE IF NOT EXISTS pasiflora.specifications (
        agent_id TEXT,
        key TEXT PRIMARY KEY,
        id TEXT,
        resource_type TEXT,
        title TEXT,
        description TEXT,
        status TEXT,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ,
        public BOOLEAN,
        max_price NUMERIC,
        min_price NUMERIC,
        have_invalid_variant_price BOOLEAN,
        video_url TEXT,
        revision INTEGER,
        category_id TEXT,
        images_ids TEXT,
        images_urls TEXT,
        created_by JSONB,
        tags JSONB,
        specvariants_id TEXT,
        specvariants_type TEXT,

        included_variant_type TEXT,
        included_variant_id TEXT,
        included_variant_title TEXT,
        included_compositions JSONB,
        included_price JSONB,
        included_composition_item_type JSONB,
        included_composition_item_id JSONB
    );
"""

# Создание таблицы bouquets_showcase
CREATE_bouquets_showcase_TABLE = """
    CREATE TABLE IF NOT EXISTS pasiflora.bouquets_showcase (
        agent_id TEXT,
        bouquet_id TEXT PRIMARY KEY,
        bouquet_title TEXT,
        bouquet_type TEXT,
        bouquet_description TEXT,
        bouquet_qty INTEGER,
        bouquet_height INTEGER,
        bouquet_width INTEGER,
        bouquet_amount NUMERIC,
        bouquet_sale_amount NUMERIC,
        bouquet_true_sale_amount NUMERIC,
        bouquet_status TEXT,
        bouquet_doc_no TEXT,
        bouquet_created_at TIMESTAMPTZ,
        bouquet_updated_at TIMESTAMPTZ,
        bouquet_on_window_at TIMESTAMPTZ,
        bouquet_completed_at TIMESTAMPTZ,
        bouquet_public BOOLEAN,
        bouquet_discount NUMERIC,
        bouquet_discount_type TEXT,
        bouquet_markup NUMERIC,
        bouquet_markup_type TEXT,
        bouquet_revision INTEGER,
        bouquet_barcode TEXT,
        
        store_id TEXT,
        created_by JSONB,
        updated_by JSONB,
        images_ids TEXT,
        images_urls TEXT,
        
        included_compositions JSONB,
        included_composition_item_type JSONB,
        included_composition_item_id JSONB

    );
"""

# Создание таблицы categories
CREATE_categories_TABLE = """
    CREATE TABLE IF NOT EXISTS pasiflora.categories (
        agent_id TEXT,
        id TEXT PRIMARY KEY,
        type TEXT,
        title TEXT,
        status TEXT,
        path JSONB,
        path_ids JSONB,
        color TEXT,
        count_public_items INTEGER,
        deleted BOOLEAN,
        revision INTEGER,
        parent JSONB,
        group_info JSONB,
        links JSONB
    );
"""

# Создание таблицы items_catalog
CREATE_items_catalog_TABLE = """
    CREATE TABLE IF NOT EXISTS pasiflora.items_catalog (
        agent_id TEXT,
        id TEXT PRIMARY KEY,
        type TEXT,
        item_id TEXT,
        item_type TEXT,
        title TEXT,
        active_points INTEGER,
        min_price NUMERIC,
        max_price NUMERIC,
        updated_at TIMESTAMP,
        public BOOLEAN,
        fractional BOOLEAN,
        revision INTEGER,
        deleted BOOLEAN,
        category_id TEXT,
        category_title TEXT,
        images_ids TEXT,
        images_urls TEXT
    );
"""

# Создание таблицы customers
CREATE_customers_TABLE = """
    CREATE TABLE IF NOT EXISTS pasiflora.customers (
        agent_id TEXT,
        id TEXT PRIMARY KEY,
        title TEXT,
        birthday TIMESTAMPTZ,
        email TEXT,
        instagram TEXT,
        status TEXT,
        is_person BOOLEAN,
        bonus_card TEXT,
        notes TEXT,
        average_check NUMERIC,
        orders_amount NUMERIC,
        orders_qty NUMERIC,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ,
        spent_points NUMERIC,
        current_points NUMERIC,
        gender TEXT,
        phone TEXT,
        revision INTEGER,
        country_code TEXT,
        bonus_group_id INTEGER
    );
"""

# Создание таблицы ordes_list
CREATE_orders_TABLE = """
    CREATE TABLE IF NOT EXISTS pasiflora.orders (
        agent_id TEXT,
        id TEXT PRIMARY KEY,
        order_type TEXT,
        status TEXT,
        order_date DATE,
        doc_no TEXT,
        description TEXT,
        budget NUMERIC,
        due_time TIMESTAMPTZ,
        delivery BOOLEAN,
        delivery_comments TEXT,
        delivery_city TEXT,
        delivery_street TEXT,
        delivery_house TEXT,
        delivery_apartment TEXT,
        delivery_building TEXT,
        delivery_time_from TIMESTAMPTZ,
        delivery_time_to TIMESTAMPTZ,
        delivery_contact TEXT,
        delivery_phone_number TEXT,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ,
        updated_status_at TIMESTAMPTZ,
        modified_at TIMESTAMPTZ,
        fiscal BOOLEAN,
        fiscalized BOOLEAN,
        by_bonuses BOOLEAN,
        posted BOOLEAN,
        posted_at TIMESTAMPTZ,
        cancel_comment TEXT,
        total_amount NUMERIC,
        payments_amount NUMERIC,
        is_external BOOLEAN,
        external_id TEXT,
        delivery_status TEXT,
        fiscalized_at TIMESTAMPTZ,
        revision INTEGER,
        amo_lead_id TEXT,
        delivery_phone_code TEXT,
        source_id TEXT,
        store_id TEXT,
        customer_id TEXT,
        posted_by_id TEXT,
        created_by_id TEXT,
        locked_by_id TEXT,
        pending_payments JSONB,
        self_link TEXT
    );
"""

async def setup_tables_pasiflora(db_conn):
    """Создает таблицы в БД внутри схемы pasiflora, если они еще не существуют.
    """
    await db_conn.execute_query(CREATE_orders_TABLE)
    await db_conn.execute_query(CREATE_customers_TABLE)
    await db_conn.execute_query(CREATE_categories_TABLE)
    await db_conn.execute_query(CREATE_items_catalog_TABLE)
    await db_conn.execute_query(CREATE_specifications_TABLE)
    await db_conn.execute_query(CREATE_bouquets_showcase_TABLE)

    logging.debug(f'Все таблицы в схеме "pasiflora" успешно созданы.')