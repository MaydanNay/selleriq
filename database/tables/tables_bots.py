CREATE_agent_knowledge_TABLE = """
    CREATE TABLE IF NOT EXISTS bots.agent_knowledge (
        business_id UUID NOT NULL,
        agent_id UUID NOT NULL,
        source_id text NOT NULL,
        type text,
        uri text,
        title text,
        status text,
        progress int,
        metadata jsonb,
        
        created_at timestamptz DEFAULT now(),
        updated_at timestamptz DEFAULT now(),
        PRIMARY KEY (business_id, agent_id, source_id)
    );
"""
CREATE_agent_knowledge_INDEX = """
    CREATE INDEX IF NOT EXISTS agent_knowledge_business_agent_idx
        ON bots.agent_knowledge (business_id, agent_id);
"""


CREATE_agent_skills_TABLE = """
    CREATE TABLE IF NOT EXISTS bots.agent_skills (
        business_id UUID NOT NULL,
        agent_id UUID NOT NULL,
        skills jsonb NOT NULL DEFAULT '[]'::jsonb,
        draft jsonb NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (business_id, agent_id)
    );
"""
CREATE_agent_skills_agent_id_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_agent_skills_agent_id ON bots.agent_skills (agent_id);
"""
CREATE_agent_skills_business_id_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_agent_skills_business_id 
        ON bots.agent_skills (business_id);
"""


CREATE_agent_instructions_TABLE = '''
    CREATE TABLE IF NOT EXISTS bots.agent_instructions(
        agent_id UUID NOT NULL,
        business_id UUID NOT NULL, 
        business_name TEXT, 
        business_niche TEXT, 
        business_description TEXT, 
        business_address TEXT, 
        business_payment TEXT, 
        business_delivery TEXT, 
        business_schedule JSONB DEFAULT '[]'::jsonb, 
        business_phones JSONB DEFAULT '[]'::jsonb,
        business_links JSONB DEFAULT '[]'::jsonb,

        created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
        updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
        
        PRIMARY KEY (agent_id),
        
        CONSTRAINT fk_agent_instructions_agent FOREIGN KEY (agent_id)
            REFERENCES bots.agent_configs(agent_id) ON DELETE CASCADE,
        CONSTRAINT fk_agent_instructions_business FOREIGN KEY (business_id)
            REFERENCES role.businesses(business_id) ON DELETE CASCADE
    );
'''
CREATE_agent_instructions_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_agent_instructions_business_id
        ON bots.agent_instructions(business_id);
"""
DROP_update_agent_instructions_updated_at_FUNCTION = """
    DROP FUNCTION IF EXISTS bots.update_agent_instructions_updated_at() CASCADE;
"""
CREATE_update_agent_instructions_updated_at_FUNCTION ="""
    CREATE OR REPLACE FUNCTION bots.update_agent_instructions_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
    AS $$
    BEGIN
    -- Присваиваем NEW.updated_at текущее время
        NEW.updated_at := NOW();
        RETURN NEW;
    END;
    $$;
"""
CREATE_trg_agent_instructions_before_update_TRIGGER = """
    CREATE TRIGGER trg_agent_instructions_before_update
        BEFORE UPDATE
        ON bots.agent_instructions
        FOR EACH ROW
        EXECUTE FUNCTION bots.update_agent_instructions_updated_at();
"""


CREATE_agent_configs_TABLE = '''
    CREATE TABLE IF NOT EXISTS bots.agent_configs(
        business_id UUID NOT NULL,
        business_name TEXT,
        crm TEXT,

        is_main BOOLEAN NOT NULL DEFAULT FALSE,
        agent_id UUID NOT NULL PRIMARY KEY,
        agent_name TEXT,
        agent_style TEXT,
        agent_model TEXT,
        agent_role_key TEXT DEFAULT 'assistant',
        agent_role TEXT DEFAULT 'AI-помощник',
        agent_channels JSONB DEFAULT '[]'::jsonb,

        agent_active BOOLEAN DEFAULT TRUE,
        agent_icon TEXT DEFAULT '/common/images/mix-logo.png',
        agent_service TEXT,
        agent_instructions TEXT,
        agent_business_data JSONB DEFAULT '[]'::jsonb,
        agent_scripts JSONB DEFAULT '[]'::jsonb,    
        agent_tools JSONB DEFAULT '[]'::jsonb,
        agent_subagents JSONB DEFAULT '[]'::jsonb,

        is_access_get_shop BOOLEAN DEFAULT FALSE,
        is_access_post_shop BOOLEAN DEFAULT FALSE,
        is_access_get_calendar BOOLEAN DEFAULT FALSE,
        is_access_post_calendar BOOLEAN DEFAULT FALSE,

        bot_access_token TEXT,
        bot_refresh_token TEXT,

        created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
        updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,

        CONSTRAINT fk_agent_configs_business FOREIGN KEY (business_id)
            REFERENCES role.businesses(business_id) ON DELETE CASCADE,

        CONSTRAINT agent_configs_business_agent_key UNIQUE (business_id, agent_id)
    );
'''
CREATE_agent_configs_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_agent_configs_business_id
        ON bots.agent_configs(business_id);
"""
CREATE_agent_configs_COMPOSITE_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_agent_configs_business_agent
        ON bots.agent_configs(business_id, agent_id);
"""
CREATE_agent_configs_channels_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_agent_configs_channels
        ON bots.agent_configs USING GIN (agent_channels);
"""

# Создание таблицы subagent_configs
CREATE_subagent_configs_TABLE = """
    CREATE TABLE IF NOT EXISTS bots.subagent_configs (
        agent_config_id UUID REFERENCES bots.agent_configs(agent_id) ON DELETE CASCADE,
        subagent_id UUID PRIMARY KEY,
        subagent_name TEXT,
        subagent_instructions JSONB DEFAULT '[]'::jsonb,
        subagent_tools JSONB DEFAULT '[]'::jsonb,
        subagent_mcp_server TEXT,

        created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
        updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
    );
"""

CREATE_contacts_TABLE = '''
    CREATE TABLE IF NOT EXISTS chats.contacts(
        user_id UUID,
        user_name TEXT,
        service TEXT,
        access_token TEXT,
        phone_id TEXT,
        contact_id UUID NOT NULL,
        contact_name TEXT,
        contact_avatar TEXT,
        thread_id UUID,
        contact_message JSONB DEFAULT '[]'::jsonb,
        user_response JSONB DEFAULT '[]'::jsonb,

        created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
        updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
    );
'''
CREATE_contact_messages_TABLE = '''
    CREATE TABLE IF NOT EXISTS chats.contact_messages(
        user_id UUID,
        user_name TEXT,
        service TEXT,
        contact_id UUID NOT NULL,
        contact_name TEXT,
        contact_message JSONB DEFAULT '[]'::jsonb,
        user_response JSONB DEFAULT '[]'::jsonb,
        thread_id UUID,

        created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
        
        PRIMARY KEY(contact_id, created_at)
    );
'''

CREATE_bot_customers_TABLE = '''
    CREATE TABLE IF NOT EXISTS bots.bot_customers(
        business_id UUID NOT NULL,
        business_name TEXT,
        agent_id UUID,
        agent_name TEXT,
        service TEXT,
        access_token TEXT,
        phone_id TEXT,
        thread_id UUID,
        project_id UUID,
        customer_id TEXT NOT NULL,
        customer_name TEXT,
        customer_avatar TEXT,
        customer_message JSONB DEFAULT '[]'::jsonb,
        manual_response BOOLEAN DEFAULT FALSE,
        manual_response_expires_at timestamp,
        assistant_response JSONB DEFAULT '[]'::jsonb,
        business_response JSONB DEFAULT '[]'::jsonb,
        last_read_at TIMESTAMP WITH TIME ZONE NULL,

        created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
        updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
        
        CONSTRAINT bot_users_agent_id_fkey FOREIGN KEY (agent_id)
            REFERENCES bots.agent_configs(agent_id) ON DELETE CASCADE,
        CONSTRAINT bot_users_business_fkey FOREIGN KEY (business_id)
            REFERENCES role.businesses(business_id) ON DELETE CASCADE
    );
'''
CREATE_bot_customers_INDEX ='''
    CREATE UNIQUE INDEX IF NOT EXISTS bot_customers_business_customer_unique
        ON bots.bot_customers (business_id, customer_id);
'''

CREATE_bot_customer_messages_TABLE = '''
    CREATE TABLE IF NOT EXISTS bots.bot_customer_messages(
        business_id UUID NOT NULL,
        business_name TEXT,
        agent_id UUID,
        agent_name TEXT,
        service TEXT,
        thread_id UUID,
        project_id UUID,
        customer_id TEXT NOT NULL,
        customer_name TEXT,
        idempotency_key TEXT,
        customer_message JSONB DEFAULT '[]'::jsonb,
        assistant_response JSONB DEFAULT '[]'::jsonb,
        business_response JSONB DEFAULT '[]'::jsonb,

        created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
        
        PRIMARY KEY(customer_id, created_at),

        CONSTRAINT bot_customer_messages_agent_fkey FOREIGN KEY (agent_id)
            REFERENCES bots.agent_configs(agent_id) ON DELETE CASCADE,
        CONSTRAINT bot_customer_messages_business_fkey FOREIGN KEY (business_id)
            REFERENCES role.businesses(business_id) ON DELETE CASCADE
    );
'''
CREATE_idx_bot_customer_messages_project_INDEX = '''
    CREATE INDEX IF NOT EXISTS idx_bot_customer_messages_project
        ON bots.bot_customer_messages (project_id);
'''
CREATE_uq_bot_customer_messages_idempotency_INDEX = """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_bot_customer_messages_idempotency
        ON bots.bot_customer_messages (business_id, customer_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL;
"""
CREATE_bot_customer_messages_UNIQUE_INDEX = '''
    CREATE INDEX IF NOT EXISTS idx_bot_customer_messages_business_customer
        ON bots.bot_customer_messages (business_id, customer_id);
'''
CREATE_bot_customer_messages_FUNCTION_AND_TRIGGER = '''
    CREATE OR REPLACE FUNCTION bots.bot_customer_messages_duplicate()
        RETURNS trigger
        LANGUAGE plpgsql
    AS $function$
    BEGIN
        SELECT agent_id, customer_name, thread_id
            INTO NEW.agent_id, NEW.customer_name, NEW.thread_id
            FROM bots.bot_customers
        WHERE customer_id = NEW.customer_id
            ORDER BY created_at DESC
            LIMIT 1;
        RETURN NEW;
    END;
    $function$;
'''
DROP_bot_customer_messages_TRIGGER = '''
    DROP TRIGGER IF EXISTS trg_bot_customer_messages_duplicate 
        ON bots.bot_customer_messages;
'''
CREATE_bot_customer_messages_TRIGGER = '''
    CREATE TRIGGER trg_bot_customer_messages_duplicate 
    BEFORE INSERT ON bots.bot_customer_messages 
    FOR EACH ROW EXECUTE FUNCTION bots.bot_customer_messages_duplicate();
'''



async def setup_tables_bots(db_conn):
    """Создает таблицы в БД внутри схемы bots, 
    если они еще не существуют.
    """
    await db_conn.execute_query(CREATE_agent_knowledge_TABLE)
    await db_conn.execute_query(CREATE_agent_knowledge_INDEX)

    await db_conn.execute_query(CREATE_agent_skills_TABLE)
    await db_conn.execute_query(CREATE_agent_skills_agent_id_INDEX)
    await db_conn.execute_query(CREATE_agent_skills_business_id_INDEX)

    # 1) Триггер-функции можно создать раньше, но триггер на таблицу создаём после таблицы.
    await db_conn.execute_query(DROP_update_agent_instructions_updated_at_FUNCTION)
    await db_conn.execute_query(CREATE_update_agent_instructions_updated_at_FUNCTION)

    # 2) Создаём основную таблицу агентов (agent_configs), другие таблицы ссылаются на неё
    await db_conn.execute_query(CREATE_agent_configs_TABLE)
    await db_conn.execute_query(CREATE_agent_configs_INDEX)
    await db_conn.execute_query(CREATE_agent_configs_COMPOSITE_INDEX)
    await db_conn.execute_query(CREATE_agent_configs_channels_INDEX)

    # 3) subagent_configs (ссылается на agent_configs)
    await db_conn.execute_query(CREATE_subagent_configs_TABLE)

    # 4) Затем agent_instructions (с FK на role.businesses)
    await db_conn.execute_query(CREATE_agent_instructions_TABLE)
    await db_conn.execute_query(CREATE_agent_instructions_INDEX)

    # 5) После того как таблица agent_instructions создана и функция существует - создаём триггер на неё
    await db_conn.execute_query(CREATE_trg_agent_instructions_before_update_TRIGGER)

    # 6) Таблицы клиентов/сообщений
    await db_conn.execute_query(CREATE_bot_customers_TABLE)
    await db_conn.execute_query(CREATE_bot_customers_INDEX)
    await db_conn.execute_query('''
        CREATE UNIQUE INDEX IF NOT EXISTS bot_customers_thread_unique
            ON bots.bot_customers(business_id, agent_id, thread_id);
    ''')

    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS bots.projects (
            business_id uuid NOT NULL,
            project_id uuid PRIMARY KEY,
            thread_id uuid NOT NULL,
            agent_id uuid NULL,
            project_name text NOT NULL,
            tools jsonb DEFAULT '{}'::jsonb,
            meta jsonb DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
    """)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_projects_business_id 
            ON bots.projects (business_id);
    """)
    await db_conn.execute_query( """
        CREATE INDEX IF NOT EXISTS idx_projects_agent_id 
            ON bots.projects (agent_id);
    """)
    await db_conn.execute_query( """
        CREATE TABLE IF NOT EXISTS bots.bot_user_messages(
            business_id UUID NOT NULL,
            business_name TEXT,
            agent_id UUID,
            agent_name TEXT,
            service TEXT,
            thread_id UUID,
            project_id UUID,
            customer_id TEXT NOT NULL,
            customer_name TEXT,
            idempotency_key TEXT,
            customer_message JSONB DEFAULT '[]'::jsonb,
            assistant_response JSONB DEFAULT '[]'::jsonb,
            business_response JSONB DEFAULT '[]'::jsonb,

            created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
            
            PRIMARY KEY (customer_id, created_at),

            CONSTRAINT bot_user_messages_agent_fkey FOREIGN KEY (agent_id)
                REFERENCES bots.agent_configs(agent_id) ON DELETE CASCADE,
            CONSTRAINT bot_user_messages_business_fkey FOREIGN KEY (business_id)
                REFERENCES role.businesses(business_id) ON DELETE CASCADE
        );
    """)

    await db_conn.execute_query(CREATE_bot_customer_messages_TABLE)
    await db_conn.execute_query(CREATE_bot_customer_messages_UNIQUE_INDEX)
    await db_conn.execute_query(CREATE_bot_customer_messages_FUNCTION_AND_TRIGGER)
    await db_conn.execute_query(DROP_bot_customer_messages_TRIGGER)
    await db_conn.execute_query(CREATE_bot_customer_messages_TRIGGER)
    await db_conn.execute_query(CREATE_idx_bot_customer_messages_project_INDEX)
    await db_conn.execute_query(CREATE_uq_bot_customer_messages_idempotency_INDEX)

    # 7) Остальные таблицы (контакты и т.д.)
    await db_conn.execute_query(CREATE_contacts_TABLE)
    await db_conn.execute_query(CREATE_contact_messages_TABLE)