import logging



CREATE_users_TABLE = """
    CREATE TABLE IF NOT EXISTS role.users (
        id SERIAL PRIMARY KEY,
        role VARCHAR(20) NOT NULL,
        mxr VARCHAR(60),
        
        user_id UUID NOT NULL UNIQUE,
        user_name VARCHAR(255),
        user_phone VARCHAR(20) UNIQUE,
        user_email VARCHAR(255),
        user_city VARCHAR(100),
        user_password TEXT,
        user_profile_avatar_image TEXT,
        user_profile_cover_image TEXT,
        user_profile_cover_position TEXT DEFAULT '0px 0px',

        is_admin BOOL DEFAULT FALSE,

        is_business BOOL DEFAULT FALSE,
        business_id UUID,
        business_owner_name VARCHAR(255),
        business_owner_phone TEXT,

        is_manager BOOL DEFAULT FALSE,
        manager_id UUID UNIQUE DEFAULT NULL,
        manager_fullname TEXT DEFAULT NULL,
        manager_whatsapp TEXT DEFAULT NULL,
        manager_telegram TEXT DEFAULT NULL,
        manager_phone VARCHAR(20) UNIQUE DEFAULT NULL,
        businesses JSONB DEFAULT '[]'::jsonb,

        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
"""

CREATE_manager_applications_TABLE = """
    CREATE TABLE IF NOT EXISTS role.manager_applications (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL,
        full_name TEXT NOT NULL,
        user_phone TEXT NOT NULL,
        email TEXT,
        comment TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
"""
CREATE_ux_manager_applications_user_pending_UNIQUE = """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_manager_applications_user_pending
        ON role.manager_applications (user_id)
        WHERE status = 'pending';
"""

CREATE_businesses_TABLE = """
    CREATE TABLE IF NOT EXISTS role.businesses (
        id SERIAL PRIMARY KEY,
        role VARCHAR(20) NOT NULL DEFAULT 'business',
        mxr VARCHAR(60) NOT NULL,
        manager_id UUID DEFAULT NULL,
        manager JSONB DEFAULT '[]'::jsonb,

        business_owner_id UUID UNIQUE,
        business_owner_name VARCHAR(255),
        business_owner_phone VARCHAR(20),
        
        user_id UUID,
        
        agent_id UUID,
        agent_name TEXT,
        
        business_tariff TEXT DEFAULT 'Spark',
        business_id UUID NOT NULL UNIQUE,
        business_name VARCHAR(255) NOT NULL,
        business_phone VARCHAR(20) NOT NULL UNIQUE,
        business_email VARCHAR(255),
        business_city VARCHAR(100),
        business_password TEXT NOT NULL,
        
        business_niche TEXT,
        business_description TEXT,
        business_address TEXT,
        business_days TEXT,
        business_hours TEXT,
        business_delivery TEXT,
        business_payment TEXT,
        business_payment_type TEXT,
        
        business_website TEXT,
        business_instagram TEXT,
        business_whatsapp TEXT,
        business_telegram TEXT,

        business_profile_avatar_image TEXT,
        business_profile_cover_image TEXT,
        business_profile_cover_position TEXT DEFAULT '0px 0px',

        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
"""
CREATE_businesses_TRIGGER = """
    DO $$
    BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_update_timestamp'
    ) THEN
        CREATE TRIGGER trg_update_timestamp
        BEFORE UPDATE ON role.businesses
        FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
    END IF;
    END;
    $$;
"""


CREATE_update_at_FUNCTION = """
    DO $do$
    BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE proname = 'update_updated_at_column'
    ) THEN
        CREATE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $fn$
        BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
        END;
        $fn$ LANGUAGE plpgsql;
    END IF;
    END;
    $do$;
"""

async def setup_tables_role(db_conn):
    """Создает таблицы в БД, если они еще не существуют"""
    await db_conn.execute_query("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    await db_conn.execute_query(CREATE_update_at_FUNCTION)
    await db_conn.execute_query(CREATE_manager_applications_TABLE)
    await db_conn.execute_query(CREATE_ux_manager_applications_user_pending_UNIQUE)

    await db_conn.execute_query(CREATE_users_TABLE)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_users_business_id
            ON role.users(business_id);
    """)
    await db_conn.execute_query("""
        DO $$
        BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'trg_update_users_timestamp'
        ) THEN
            CREATE TRIGGER trg_update_users_timestamp
            BEFORE UPDATE ON role.users
            FOR EACH ROW
            EXECUTE PROCEDURE update_updated_at_column();
        END IF;
        END;
        $$;
    """)


    await db_conn.execute_query(CREATE_businesses_TABLE)
    await db_conn.execute_query(CREATE_businesses_TRIGGER)

    # Создаем таблицу для бизнес-пользователей
    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS role.business_users (
            id SERIAL PRIMARY KEY,
            user_id UUID NOT NULL DEFAULT gen_random_uuid(),
            business_id UUID NOT NULL REFERENCES role.businesses(business_id) ON DELETE CASCADE,
            fullname VARCHAR(255),
            phone VARCHAR(20) NOT NULL,
            is_owner BOOLEAN NOT NULL DEFAULT FALSE,
                                
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    # для быстрого поиска по бизнесу
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_business_users_business 
            ON role.business_users(business_id)
    """)
    
    await db_conn.execute_query("""
        CREATE UNIQUE INDEX IF NOT EXISTS business_users_unique
            ON role.business_users(user_id, business_id);
    """)

    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS role.demo_access_numbers (
            id SERIAL PRIMARY KEY,
            phone TEXT NOT NULL UNIQUE,
            name TEXT, 
            allowed BOOLEAN NOT NULL DEFAULT TRUE,
            added_by UUID,
            added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            note TEXT
        );
    """)
    logging.debug(f'Все таблицы в схеме "role" успешно созданы.')
