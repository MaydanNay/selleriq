CREATE_notifications_TABLE = """
    CREATE TABLE IF NOT EXISTS mxr.notifications (
        id BIGSERIAL PRIMARY KEY,
        mxr TEXT NOT NULL,
        type TEXT NOT NULL,                      -- 'order', позже можно добавить другие типы
        payload JSONB,                           -- данные о заказе (товары и т.п.)
        customer_name TEXT,
        customer_phone TEXT,
        customer_comment TEXT,
        created_at TIMESTAMPTZ DEFAULT now(),
        is_read BOOLEAN DEFAULT FALSE
    );
"""

CREATE_orders_TABLE = """
    CREATE TABLE IF NOT EXISTS mxr.orders (
        id BIGSERIAL PRIMARY KEY,
        mxr TEXT NOT NULL,
        payload JSONB NOT NULL,            -- полный санитизированный cart и метаданные
        customer_name TEXT,
        customer_phone TEXT,
        customer_comment TEXT,
        total NUMERIC(12,2) DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'new', -- new, processing, sent, cancelled и т.д.
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ
    );
"""


CREATE_calendar_TABLE = """
    CREATE TABLE IF NOT EXISTS mxr.calendar (
        id SERIAL PRIMARY KEY,
        role VARCHAR(20) NOT NULL DEFAULT 'user',
        user_id UUID NOT NULL,

        task_id UUID NOT NULL UNIQUE,
        title TEXT NOT NULL,
        description TEXT,
        start_date DATE NOT NULL,
        end_date DATE,
        start_time TIME NOT NULL,
        end_time TIME,
        status TEXT NOT NULL DEFAULT 'none',

        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
"""

CREATE_mixlink_TABLE = """
    CREATE TABLE IF NOT EXISTS mxr.mixlink (
        id SERIAL PRIMARY KEY,
        role VARCHAR(20) NOT NULL DEFAULT 'user',
        mxr VARCHAR(60) NOT NULL UNIQUE,
        owner_id UUID NOT NULL UNIQUE,
        
        mixlink_name VARCHAR(255),
        mixlink_niche TEXT,
        mixlink_description TEXT,
        
        links JSONB DEFAULT '[]'::jsonb,
        blocks JSONB DEFAULT '[]'::jsonb,
        products JSONB DEFAULT '[]'::jsonb,

        profile_avatar_image TEXT,
        profile_cover_image TEXT,
        profile_cover_position TEXT DEFAULT '0px 0px',

        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
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

CREATE_mixlink_TRIGGER = """
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

async def setup_tables_mixlink(db_conn):
    """Создает таблицы в БД, если они еще не существуют"""
    await db_conn.execute_query(CREATE_update_at_FUNCTION)
    await db_conn.execute_query(CREATE_mixlink_TABLE)
    await db_conn.execute_query(CREATE_mixlink_TRIGGER)
    await db_conn.execute_query(CREATE_calendar_TABLE)

    await db_conn.execute_query(CREATE_notifications_TABLE)
    await db_conn.execute_query(CREATE_orders_TABLE)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_orders_mxr_created 
            ON mxr.orders (mxr, created_at DESC);
    """)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_orders_status 
            ON mxr.orders (status);
    """)

    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS mxr.knowledge (
            owner_id UUID NOT NULL,
            source_id text NOT NULL,
            type text,
            uri text,
            title text,
            status text,
            progress int,
            metadata jsonb,
            
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now(),
            PRIMARY KEY (owner_id, source_id)
        );
    """)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_mxr_knowledge_owner_created 
            ON mxr.knowledge(owner_id, created_at DESC);
    """)

    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS agents.community_agents (
            agent_id TEXT PRIMARY KEY,
            business_id TEXT,
            agent_name TEXT,
            agent_role TEXT,
            agent_tools JSONB,
            config JSONB,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        );
    """)

    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS agents.community_posts (
            post_id UUID PRIMARY KEY,
            thread_id UUID,
            content TEXT NOT NULL,
            access TEXT DEFAULT 'public',
            request_type TEXT DEFAULT 'other',
            attachments JSONB DEFAULT '[]'::jsonb,
            created TIMESTAMPTZ DEFAULT now(),
            like_count INTEGER DEFAULT 0,
            dislike_count INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0,
            task_id TEXT
        );
    """)

    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_community_posts_created 
            ON agents.community_posts (created DESC);
    """)

    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS agents.community_post_comments (
            comment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            post_id uuid NOT NULL REFERENCES agents.community_posts(post_id) ON DELETE CASCADE,
            parent_id UUID,
            author_id uuid NULL,
            author_name TEXT,
            author_gender TEXT,
            author_avatar TEXT,
            text TEXT NOT NULL,
            created timestamptz DEFAULT now()
        );
    """)    
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_community_post_comments
            ON agents.community_post_comments(post_id, created DESC);
    """)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_post_comments_post_id 
            ON agents.community_post_comments(post_id);
    """)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_post_comments_parent_id 
            ON agents.community_post_comments(post_id, parent_id);
    """)

    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS agents.community_comment_reactions (
            comment_id UUID NOT NULL,
            user_id TEXT NOT NULL,
            reaction SMALLINT NOT NULL CHECK (reaction IN (1, -1)),
            created TIMESTAMP WITH TIME ZONE DEFAULT now(),
            PRIMARY KEY (comment_id, user_id)
        );
    """)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_comment_reactions_comment_id 
            ON agents.community_comment_reactions(comment_id);
    """)

    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS agents.community_post_reactions (
            post_id uuid NOT NULL REFERENCES agents.community_posts(post_id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            reaction smallint NOT NULL, -- 1 = like, -1 = dislike
            created timestamptz DEFAULT now(),
            PRIMARY KEY (post_id, user_id)
        );
    """)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_community_post_reactions
            ON agents.community_post_reactions(post_id);
    """)