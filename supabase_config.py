"""Supabase数据库配置"""
import psycopg2
from psycopg2.extras import RealDictCursor

DB_CONFIG = {
    "host": "aws-0-ap-northeast-1.pooler.supabase.com",
    "port": 6543,
    "database": "postgres",
    "user": "postgres.kohuwtvxfvgbjdbmszao",
    "password": "***",
    "connect_timeout": 10
}

def get_db():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def init_db():
    pass
