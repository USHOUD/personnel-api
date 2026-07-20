"""Supabase数据库配置"""
import psycopg2
from psycopg2.extras import RealDictCursor

DB_CONFIG = {
    "host": "aws-0-ap-northeast-1.pooler.supabase.com",
    "port": 6543,
    "database": "postgres",
    "user": "postgres.kohuwtvxfvgbjdbmszao",
    "password": "ahkNuymJI7iYYLQj",
    "connect_timeout": 10
}

def get_db():
    """获取数据库连接"""
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def init_db():
    """初始化数据库表"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS personnel (
        id VARCHAR(10) PRIMARY KEY,
        name VARCHAR(50) NOT NULL,
        gender VARCHAR(10),
        id_card VARCHAR(30),
        birth VARCHAR(20),
        edu VARCHAR(20),
        hometown VARCHAR(50),
        position VARCHAR(100),
        project VARCHAR(50) DEFAULT '未分配',
        phone VARCHAR(20),
        cert TEXT,
        category VARCHAR(20),
        salary NUMERIC,
        status VARCHAR(20) DEFAULT '在岗',
        status_detail VARCHAR(100) DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS transfers (
        id VARCHAR(10) PRIMARY KEY,
        person_id VARCHAR(10),
        person_name VARCHAR(50),
        from_project VARCHAR(50),
        to_project VARCHAR(50),
        transfer_date VARCHAR(20),
        notes TEXT,
        created_at VARCHAR(30)
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS leave_records (
        id VARCHAR(10) PRIMARY KEY,
        person_id VARCHAR(10),
        person_name VARCHAR(50),
        start_date VARCHAR(20),
        end_date VARCHAR(20),
        reason TEXT,
        status VARCHAR(20) DEFAULT '待审批',
        created_at VARCHAR(30)
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS trip_records (
        id VARCHAR(10) PRIMARY KEY,
        person_id VARCHAR(10),
        person_name VARCHAR(50),
        destination VARCHAR(100),
        start_date VARCHAR(20),
        end_date VARCHAR(20),
        reason TEXT,
        status VARCHAR(20) DEFAULT '待审批',
        created_at VARCHAR(30)
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        phone VARCHAR(20) PRIMARY KEY,
        name VARCHAR(50),
        password VARCHAR(100),
        is_admin BOOLEAN DEFAULT FALSE
    );
    """)
    
    cur.execute("""
    INSERT INTO users (phone, name, password, is_admin) 
    VALUES ('18184005669', '管理员', '123456', TRUE)
    ON CONFLICT (phone) DO NOTHING;
    """)
    
    # 一建考取指标表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_targets (
        id SERIAL PRIMARY KEY,
        exam_type VARCHAR(20) NOT NULL,
        year INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(exam_type, year)
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_target_persons (
        id SERIAL PRIMARY KEY,
        target_id INTEGER REFERENCES exam_targets(id),
        person_name VARCHAR(50) NOT NULL,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    
    conn.commit()
    cur.close()
    conn.close()
