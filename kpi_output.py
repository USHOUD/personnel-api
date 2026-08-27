"""KPI考核 + 产值看板 + 综合考核 API
Kimi优化版 v2（修复装饰器重复查询、SQL性能、Decimal重复、日志重复等问题）
"""
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, Union

from flask import Blueprint, jsonify, request
from supabase_config import get_db

bp = Blueprint('kpi_output', __name__)
logger = logging.getLogger(__name__)

# ============= 常量配置 =============

# 权限相关
SUPER_ADMIN_PHONE: str = '18184005669'
PRODUCTION_ADMIN_PHONE: str = '15196251135'
LEADER_PHONES: Dict[str, str] = {
    '18523176628': '邱方恒',
    '13980885726': '廖志成',
    '17636671760': '吕亮',
    '18382194536': '李强',
}

# 权重与比例
DEFAULT_TASK_WEIGHT: Decimal = Decimal('10')
KPI_WEIGHT_RATIO: Decimal = Decimal('0.6')
EVAL_WEIGHT_RATIO: Decimal = Decimal('0.4')
OUTPUT_WEIGHT_RATIO: Decimal = Decimal('0.6')

# 部门/职位过滤
PROJECT_DEPT_EXCLUDE: set = {'后台', '未分配', ''}
POSITION_EXCLUDE_PATTERNS: Tuple[str, ...] = ('%司机%', '%实习%', '%见习%')

# 状态枚举
STATUS_COMPLETED: str = '已完成'
STATUS_APPROVED: str = 'approved'
STATUS_PENDING: str = 'pending'
STATUS_ACTIVE: str = 'active'
STATUS_REJECTED: str = 'rejected'

# 产值看板机构分类
PROJECT_DEPT_KEYWORDS = ['项目', '站', '片区', '标段']
DISPATCH_DEPTS = {'供应链分中心', '预算中心', '其他'}


# ============= 基础工具函数（新增） =============

def to_decimal(value: Any, default: Decimal = Decimal('0')) -> Decimal:
    """安全地将任意值转为 Decimal"""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def safe_divide(numerator: Any, denominator: Any, multiplier: Decimal = Decimal('1')) -> Decimal:
    """安全除法，避免 ZeroDivisionError"""
    num = to_decimal(numerator)
    den = to_decimal(denominator)
    if den <= 0:
        return Decimal('0')
    return (num / den * multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def get_month_range(year_month: str) -> Tuple[str, str]:
    """将 YYYY-MM 转为日期范围字符串（用于SQL范围查询）

    替代低效的 TO_CHAR(column, 'YYYY-MM') = %s，利用索引加速
    """
    year, month = map(int, year_month.split('-'))
    start = f"{year_month}-01"
    if month == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{str(month + 1).zfill(2)}-01"
    return start, end


def get_period_from_date(date_str: str = '') -> str:
    """从日期字符串获取YYYY-MM格式"""
    if not date_str:
        return datetime.now().strftime('%Y-%m')
    try:
        return datetime.strptime(date_str[:10], '%Y-%m-%d').strftime('%Y-%m')
    except Exception:
        return datetime.now().strftime('%Y-%m')


# ============= 健康检查（防云托管冷启动） =============

@bp.route('/api/health', methods=['GET'])
def health_check() -> Tuple[Dict[str, Any], int]:
    """轻量级健康检查端点

    用途：
    - 给监控/cron 每 5 分钟调用一次，避免云托管实例冷启动
    - 检查数据库连接是否正常

    Returns:
        {status: 'ok', db: 'ok'/'error', timestamp: ISO格式}
    """
    db_status = 'ok'
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT 1")
    except Exception as e:
        logger.error(f"健康检查DB失败: {e}")
        db_status = 'error'

    status_code = 200 if db_status == 'ok' else 503
    return jsonify({
        'status': 'ok' if db_status == 'ok' else 'degraded',
        'db': db_status,
        'timestamp': datetime.now().isoformat()
    }), status_code


def format_datetime(dt: Any) -> str:
    """格式化日期时间为字符串"""
    return str(dt) if dt else ''


def format_task_dates(tasks: List[Dict[str, Any]]) -> None:
    """格式化任务列表中的日期和权重字段（原地修改）"""
    for t in tasks:
        t['created_at'] = format_datetime(t.get('created_at'))
        t['updated_at'] = format_datetime(t.get('updated_at'))
        t['weight'] = float(to_decimal(t.get('weight'), DEFAULT_TASK_WEIGHT))


def format_doc_dates(docs: List[Dict[str, Any]]) -> None:
    """格式化验收资料日期字段（原地修改）"""
    for d in docs:
        d['uploaded_at'] = format_datetime(d.get('uploaded_at'))
        d['reviewed_at'] = format_datetime(d.get('reviewed_at'))


def is_project_department(project: Optional[str]) -> bool:
    """判断是否为项目部（非后台/未分配）"""
    return bool(project and project not in PROJECT_DEPT_EXCLUDE)


def classify_org(dept: str) -> Tuple[str, str]:
    """判断部门所属机构类别

    Returns:
        (org_category, org_name)
        org_category: 'project_dept' | 'dispatch' | 'headquarters_office'
    """
    if not dept:
        return 'headquarters_office', '未分配'
    if any(kw in dept for kw in PROJECT_DEPT_KEYWORDS):
        return 'project_dept', dept
    if dept in DISPATCH_DEPTS:
        return 'dispatch', dept
    return 'headquarters_office', dept


def classify_person_level(cat: str, pos: str, is_ext: bool) -> str:
    """判断人员层级

    Returns:
        'team' | 'staff' | 'outsource' | 'external'
    """
    if is_ext:
        return 'external'
    if cat in ('C1', 'C2'):
        return 'outsource'
    is_management = (
        ('副' in pos) or ('经理' in pos) or ('书记' in pos) or
        ('部长' in pos) or ('主任' in pos) or ('负责人' in pos) or ('主管' in pos)
    )
    if cat == '正式职工' and is_management:
        return 'team'
    return 'staff'


# ============= 数据库上下文管理器（简化版） =============

class DatabaseContext:
    """数据库连接上下文管理器，自动处理提交、回滚和关闭

    注意：异常在 __exit__ 中已记录日志并回滚，外层不再需要 try/except 包裹
    """

    def __init__(self) -> None:
        self.conn = None
        self.cur = None

    def __enter__(self):
        self.conn = get_db()
        self.cur = self.conn.cursor()
        return self.cur

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cur:
            self.cur.close()
        if self.conn:
            if exc_type is not None:
                self.conn.rollback()
                # 只在 __exit__ 记录一次日志，外层不再重复记录
                logger.error(f"数据库操作异常（已回滚）: {exc_val}", exc_info=True)
            else:
                self.conn.commit()
            self.conn.close()
        return False  # 不吞掉异常，继续向上抛出


def get_db_cursor():
    """获取数据库游标的上下文管理器"""
    return DatabaseContext()


# ============= 权限装饰器（修复重复查询） =============

def login_required(f):
    """登录校验装饰器

    将 user 对象注入被装饰函数的第一个参数，后续装饰器可直接使用
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '未登录'}), 401
        return f(user, *args, **kwargs)
    return decorated


def admin_required(f):
    """管理员权限装饰器（依赖 login_required 已注入的 user）"""
    @wraps(f)
    def decorated(user: Dict[str, Any], *args, **kwargs):
        if not has_management_right(user['phone']):
            return jsonify({'error': '无权限'}), 403
        return f(user, *args, **kwargs)
    # 注意：admin_required 必须配合 login_required 使用
    # 使用方式：@login_required -> @admin_required
    return decorated


def reviewer_required(f):
    """审核权限装饰器（依赖 login_required 已注入的 user）"""
    @wraps(f)
    def decorated(user: Dict[str, Any], *args, **kwargs):
        if not is_reviewer(user['phone']):
            return jsonify({'error': '无审核权限'}), 403
        return f(user, *args, **kwargs)
    return decorated


# ============= 基础工具函数 =============

def get_current_user() -> Optional[Dict[str, Any]]:
    """从请求头获取当前用户信息"""
    phone = request.headers.get('X-User-Phone', '')
    if not phone:
        return None
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT phone, name, is_admin FROM users WHERE phone=%s", (phone,))
            return cur.fetchone()
    except Exception as e:
        logger.error(f"获取当前用户失败: {e}", exc_info=True)
        return None


def get_my_person(cur, phone: str) -> Optional[Dict[str, Any]]:
    """获取当前用户的personnel信息"""
    cur.execute("SELECT * FROM personnel WHERE phone=%s", (phone,))
    return cur.fetchone()


def has_management_right(user_phone: str) -> bool:
    """是否有管理权限（超管+生产管理员+4领导班子）"""
    return (
        user_phone == SUPER_ADMIN_PHONE
        or user_phone == PRODUCTION_ADMIN_PHONE
        or user_phone in LEADER_PHONES
    )


def is_reviewer(user_phone: str) -> bool:
    """是否有审核权限（超管+4领导班子）"""
    return user_phone == SUPER_ADMIN_PHONE or user_phone in LEADER_PHONES


# ============= 核心计算函数（用 to_decimal/safe_divide 重构） =============

def calculate_kpi_from_tasks(tasks: List[Dict[str, Any]]) -> Decimal:
    """根据任务列表计算KPI得分（0-100）"""
    total_weight = Decimal('0')
    earned = Decimal('0')
    for t in tasks:
        w = to_decimal(t.get('weight'), DEFAULT_TASK_WEIGHT)
        total_weight += w
        prog = to_decimal(t.get('progress'))
        st = t.get('status') or ''
        if st == STATUS_COMPLETED or prog >= 100:
            earned += w * Decimal('100')
        else:
            earned += w * prog
    return safe_divide(earned, total_weight)


def calculate_kpi_score(cur, assignee_name: str, period: str) -> Decimal:
    """从数据库查询并计算个人KPI得分（0-100）"""
    cur.execute("""
        SELECT
            COALESCE(SUM(weight), 0) AS total_weight,
            COALESCE(SUM(CASE
                WHEN status=%s OR COALESCE(progress,0)>=100 THEN weight*100
                ELSE weight*COALESCE(progress,0)
            END), 0) AS earned
        FROM tasks
        WHERE assignee=%s
          AND (kpi_period=%s OR (kpi_period='' AND TO_CHAR(created_at, 'YYYY-MM')=%s))
    """, (STATUS_COMPLETED, assignee_name, period, period))
    row = cur.fetchone()
    return safe_divide(row['earned'], row['total_weight'])


def calculate_output_score(cur, dept: str, period: str) -> Decimal:
    """计算项目部产值完成率得分（0-100）

    使用日期范围查询替代 TO_CHAR，提升性能
    """
    if not dept or dept in PROJECT_DEPT_EXCLUDE:
        return Decimal('0')

    start_date, end_date = get_month_range(period)
    cur.execute("""
        SELECT
            COALESCE(SUM(pl.planned_output), 0) AS planned,
            COALESCE(SUM(CASE WHEN a.review_status=%s THEN a.output_value ELSE 0 END), 0) AS actual
        FROM projects p
        LEFT JOIN project_output_plans pl ON pl.project_id=p.id AND pl.year_month=%s
        LEFT JOIN acceptance_docs a ON a.project_id=p.id
            AND a.uploaded_at >= %s AND a.uploaded_at < %s
        WHERE p.dept=%s AND p.status=%s
    """, (STATUS_APPROVED, period, start_date, end_date, dept, STATUS_ACTIVE))
    row = cur.fetchone()
    return safe_divide(row['actual'], row['planned'], Decimal('100'))


def calculate_eval_score(
    cur,
    person_id: Union[int, str],
    cycle_id: Optional[int] = None
) -> Tuple[Decimal, int]:
    """计算360评价平均分（指定周期内的）"""
    if cycle_id is None:
        cycle_id = get_latest_closed_cycle_id(cur)
    if cycle_id is None:
        return Decimal('0'), 0

    cur.execute("""
        SELECT AVG(total_score) AS avg_score, COUNT(*) AS cnt
        FROM evaluation_scores
        WHERE evaluatee_id=%s AND cycle_id=%s
    """, (person_id, cycle_id))
    row = cur.fetchone()
    avg = row['avg_score'] or 0
    cnt = row['cnt'] or 0
    return to_decimal(avg), cnt


def get_latest_closed_cycle_id(cur) -> Optional[int]:
    """获取最近已关闭的考核周期ID"""
    cur.execute("""
        SELECT id FROM evaluation_cycles
        WHERE status='closed'
        ORDER BY id DESC LIMIT 1
    """)
    row = cur.fetchone()
    return row['id'] if row else None


def get_cycle_info(cur, cycle_id: int) -> Optional[Dict[str, Any]]:
    """获取考核周期信息"""
    cur.execute("SELECT id, name, period, status FROM evaluation_cycles WHERE id=%s", (cycle_id,))
    return cur.fetchone()


def calculate_final_score(
    kpi_score: Decimal,
    output_score: Decimal,
    eval_score: Decimal,
    is_project_dept: bool
) -> Decimal:
    """计算综合考核分"""
    if is_project_dept:
        final = output_score * OUTPUT_WEIGHT_RATIO + eval_score * EVAL_WEIGHT_RATIO
    else:
        final = kpi_score * KPI_WEIGHT_RATIO + eval_score * EVAL_WEIGHT_RATIO
    return final.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ============= KPI 接口 =============

@bp.route('/api/kpi/my-tasks', methods=['GET'])
@login_required
def kpi_my_tasks(user: Dict[str, Any]) -> Tuple[Any, int]:
    """当前用户某月KPI任务列表（含分数）"""
    period = request.args.get('period', get_period_from_date())

    try:
        with get_db_cursor() as cur:
            me = get_my_person(cur, user['phone'])
            if not me:
                return jsonify({
                    'tasks': [],
                    'kpi_score': 0,
                    'period': period,
                    'task_count': 0,
                    'total_weight': 0,
                    'completed_count': 0
                }), 200

            cur.execute("""
                SELECT id, title, content, status, progress, weight, source, deadline,
                       created_at, updated_at, publisher_name, kpi_period
                FROM tasks
                WHERE assignee=%s
                  AND (kpi_period=%s OR (kpi_period='' AND TO_CHAR(created_at, 'YYYY-MM')=%s))
                ORDER BY created_at DESC
            """, (me['name'], period, period))
            tasks = cur.fetchall()

            kpi_score = calculate_kpi_from_tasks(tasks)
            format_task_dates(tasks)

            total_weight = sum(
                to_decimal(t.get('weight'), DEFAULT_TASK_WEIGHT) for t in tasks
            )
            completed_count = sum(
                1 for t in tasks
                if t.get('status') == STATUS_COMPLETED or (t.get('progress') or 0) >= 100
            )

            return jsonify({
                'tasks': tasks,
                'kpi_score': float(kpi_score),
                'period': period,
                'task_count': len(tasks),
                'total_weight': float(total_weight),
                'completed_count': completed_count
            }), 200
    except Exception:
        # DatabaseContext.__exit__ 已记录日志并回滚，这里只需返回友好错误
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/kpi/team-summary', methods=['GET'])
@login_required
@admin_required
def kpi_team_summary(user: Dict[str, Any]) -> Tuple[Any, int]:
    """团队某月KPI汇总（管理员可见）"""
    period = request.args.get('period', get_period_from_date())

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT p.id, p.name, p.dept, p.project, p.position,
                       COUNT(t.id) AS task_count,
                       COALESCE(SUM(t.weight), 0) AS total_weight,
                       COALESCE(SUM(CASE
                           WHEN t.status=%s OR COALESCE(t.progress,0)>=100 THEN t.weight*100
                           ELSE t.weight*COALESCE(t.progress,0)
                       END), 0) AS earned
                FROM personnel p
                LEFT JOIN tasks t ON t.assignee=p.name
                    AND (t.kpi_period=%s OR (t.kpi_period='' AND TO_CHAR(t.created_at, 'YYYY-MM')=%s))
                WHERE (p.leave_date IS NULL OR leave_date='')
                  AND p.position NOT LIKE %s
                  AND p.position NOT LIKE %s
                  AND p.position NOT LIKE %s
                GROUP BY p.id, p.name, p.dept, p.project, p.position
                ORDER BY earned DESC NULLS LAST
            """, (
                STATUS_COMPLETED, period, period,
                *POSITION_EXCLUDE_PATTERNS
            ))
            rows = cur.fetchall()

            result = []
            for r in rows:
                score = safe_divide(r['earned'], r['total_weight'])
                result.append({
                    'id': r['id'],
                    'name': r['name'],
                    'dept': r.get('dept') or '',
                    'project': r.get('project') or '',
                    'position': r.get('position') or '',
                    'task_count': r.get('task_count') or 0,
                    'kpi_score': float(score)
                })

            return jsonify({'period': period, 'summary': result}), 200
    except Exception:
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/kpi/update-source', methods=['POST'])
@login_required
def update_task_kpi_source(user: Dict[str, Any]) -> Tuple[Any, int]:
    """更新任务的KPI来源（任务发布时自动调用）"""
    data = request.json or {}
    task_id = data.get('task_id')
    source = data.get('source', 'manual')
    weight = data.get('weight', 10)
    kpi_period = data.get('kpi_period', get_period_from_date())

    if not task_id:
        return jsonify({'error': '缺少task_id'}), 400

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE tasks SET source=%s, weight=%s, kpi_period=%s
                WHERE id=%s
            """, (source, weight, kpi_period, task_id))
            return jsonify({'success': True}), 200
    except Exception:
        return jsonify({'error': '更新失败，请稍后重试'}), 500


# ============= 项目管理接口 =============

@bp.route('/api/projects', methods=['GET'])
@login_required
def list_projects(user: Dict[str, Any]) -> Tuple[Any, int]:
    """项目列表"""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT p.*, per.name AS manager_name
                FROM projects p
                LEFT JOIN personnel per ON per.id=p.manager_id
                ORDER BY p.id DESC
            """)
            projects = cur.fetchall()
            for p in projects:
                p['created_at'] = format_datetime(p.get('created_at'))
            return jsonify(projects), 200
    except Exception:
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/projects', methods=['POST'])
@login_required
@admin_required
def create_project(user: Dict[str, Any]) -> Tuple[Any, int]:
    """新建项目（仅管理员）"""
    data = request.json or {}

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO projects
                    (name, dept, manager_id, manager_phone, total_contract_value, start_date, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                data.get('name', ''),
                data.get('dept', ''),
                data.get('manager_id', ''),
                data.get('manager_phone', ''),
                data.get('total_contract_value', 0),
                data.get('start_date', ''),
                user['phone']
            ))
            pid = cur.fetchone()['id']
            return jsonify({'success': True, 'id': pid}), 200
    except Exception:
        return jsonify({'error': '创建失败，请稍后重试'}), 500


@bp.route('/api/projects/<int:pid>', methods=['GET'])
@login_required
def get_project(user: Dict[str, Any], pid: int) -> Tuple[Any, int]:
    """项目详情（含节点、计划、产值）"""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT p.*, per.name AS manager_name
                FROM projects p
                LEFT JOIN personnel per ON per.id=p.manager_id
                WHERE p.id=%s
            """, (pid,))
            project = cur.fetchone()
            if not project:
                return jsonify({'error': '项目不存在'}), 404

            project['created_at'] = format_datetime(project.get('created_at'))

            cur.execute("""
                SELECT * FROM project_nodes
                WHERE project_id=%s
                ORDER BY id
            """, (pid,))
            nodes = cur.fetchall()
            for n in nodes:
                n['created_at'] = format_datetime(n.get('created_at'))
            project['nodes'] = nodes

            cur.execute("""
                SELECT * FROM project_output_plans
                WHERE project_id=%s
                ORDER BY year_month DESC
            """, (pid,))
            plans = cur.fetchall()
            project['plans'] = plans

            return jsonify(project), 200
    except Exception:
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/projects/<int:pid>/nodes', methods=['POST'])
@login_required
@admin_required
def add_node(user: Dict[str, Any], pid: int) -> Tuple[Any, int]:
    """添加项目节点（仅管理员）"""
    data = request.json or {}

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO project_nodes
                    (project_id, node_name, planned_date, planned_output, weight)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                pid,
                data.get('node_name', ''),
                data.get('planned_date', ''),
                data.get('planned_output', 0),
                data.get('weight', 10)
            ))
            nid = cur.fetchone()['id']
            return jsonify({'success': True, 'id': nid}), 200
    except Exception:
        return jsonify({'error': '添加失败，请稍后重试'}), 500


@bp.route('/api/projects/<int:pid>/nodes/<int:nid>', methods=['PUT'])
@login_required
def update_node(user: Dict[str, Any], pid: int, nid: int) -> Tuple[Any, int]:
    """更新项目节点"""
    data = request.json or {}
    allowed_fields = ['node_name', 'planned_date', 'actual_date', 'planned_output', 'status', 'weight']

    updates = []
    params = []
    for field in allowed_fields:
        if field in data:
            updates.append(f"{field}=%s")
            params.append(data[field])

    if not updates:
        return jsonify({'success': True}), 200

    params.extend([nid, pid])

    try:
        with get_db_cursor() as cur:
            cur.execute(f"""
                UPDATE project_nodes
                SET {', '.join(updates)}
                WHERE id=%s AND project_id=%s
            """, params)
            return jsonify({'success': True}), 200
    except Exception:
        return jsonify({'error': '更新失败，请稍后重试'}), 500


# ============= 产值计划/实际接口 =============

@bp.route('/api/output/plans', methods=['GET'])
@login_required
def get_output_plan(user: Dict[str, Any]) -> Tuple[Any, int]:
    """获取某项目某月产值计划"""
    project_id = request.args.get('project_id', type=int)
    year_month = request.args.get('year_month', get_period_from_date())

    if not project_id:
        return jsonify({'error': '缺少project_id'}), 400

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT * FROM project_output_plans
                WHERE project_id=%s AND year_month=%s
            """, (project_id, year_month))
            plan = cur.fetchone()
            return jsonify(plan or {}), 200
    except Exception:
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/output/plans', methods=['POST'])
@login_required
@admin_required
def upsert_output_plan(user: Dict[str, Any]) -> Tuple[Any, int]:
    """创建/更新产值计划（仅管理员）"""
    data = request.json or {}
    project_id = data.get('project_id')
    year_month = data.get('year_month')
    planned_output = data.get('planned_output', 0)
    notes = data.get('notes', '')

    if not project_id or not year_month:
        return jsonify({'error': '缺少project_id或year_month'}), 400

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO project_output_plans
                    (project_id, year_month, planned_output, notes, created_by, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (project_id, year_month)
                DO UPDATE SET planned_output=EXCLUDED.planned_output,
                              notes=EXCLUDED.notes,
                              updated_at=NOW()
            """, (project_id, year_month, planned_output, notes, user['phone']))
            return jsonify({'success': True}), 200
    except Exception:
        return jsonify({'error': '更新失败，请稍后重试'}), 500


@bp.route('/api/output/dashboard', methods=['GET'])
@login_required
def output_dashboard(user: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """产值看板：所有项目部本月完成情况

    分级结构：
    - 项目部（一线项目）：康定、成都北站、遂宁站等
    - 安装公司机关：
      - 派出机构：供应链中心、预算中心、其他
      - 机关本部：综合办、商务法务部、财务部等
    """
    year_month = request.args.get('year_month', get_period_from_date())
    start_date, end_date = get_month_range(year_month)

    try:
        with get_db_cursor() as cur:
            # 使用日期范围查询替代 TO_CHAR，性能提升
            cur.execute("""
                SELECT
                    p.id, p.name, p.dept, p.total_contract_value, per.name AS manager_name,
                    pl.planned_output,
                    COALESCE(SUM(CASE WHEN a.review_status=%s THEN a.output_value ELSE 0 END), 0) AS actual_output,
                    COUNT(CASE WHEN a.review_status=%s THEN 1 END) AS pending_docs
                FROM projects p
                LEFT JOIN personnel per ON per.id = p.manager_id
                LEFT JOIN project_output_plans pl ON pl.project_id = p.id AND pl.year_month = %s
                LEFT JOIN acceptance_docs a ON a.project_id = p.id
                    AND a.uploaded_at >= %s AND a.uploaded_at < %s
                WHERE p.status = %s
                GROUP BY p.id, p.name, p.dept, p.total_contract_value, per.name, pl.planned_output
                ORDER BY p.dept, p.name
            """, (STATUS_APPROVED, STATUS_PENDING, year_month, start_date, end_date, STATUS_ACTIVE))
            projects = cur.fetchall()

            result = []
            by_org_name: Dict[str, Dict[str, Any]] = {}

            for p in projects:
                planned = to_decimal(p.get('planned_output'))
                actual = to_decimal(p.get('actual_output'))
                progress = safe_divide(actual, planned, Decimal('100'))
                dept = p.get('dept') or '未分配'
                org_cat, org_name = classify_org(dept)

                item = {
                    'id': p['id'],
                    'name': p['name'],
                    'dept': dept,
                    'org_category': org_cat,
                    'org_name': org_name,
                    'total_contract_value': float(to_decimal(p.get('total_contract_value'))),
                    'manager_name': p.get('manager_name') or '',
                    'planned_output': float(planned),
                    'actual_output': float(actual),
                    'progress': float(progress),
                    'pending_docs': p.get('pending_docs') or 0
                }
                result.append(item)

                # 按 org_name 聚合
                if org_name not in by_org_name:
                    by_org_name[org_name] = {
                        'name': org_name,
                        'category': org_cat,
                        'projects': [],
                        'planned': Decimal('0'),
                        'actual': Decimal('0'),
                        'project_count': 0
                    }
                g = by_org_name[org_name]
                g['projects'].append(item)
                g['planned'] += planned
                g['actual'] += actual
                g['project_count'] += 1

            # 计算每个 org_name 的汇总
            org_groups = {}
            for name, g in by_org_name.items():
                org_groups[name] = {
                    'name': name,
                    'category': g['category'],
                    'project_count': g['project_count'],
                    'planned': float(g['planned']),
                    'actual': float(g['actual']),
                    'progress': float(safe_divide(g['actual'], g['planned'], Decimal('100'))),
                    'projects': g['projects']
                }

            # 构建两级结构
            def build_org_summary(cat: str, name: str, subgroups: List[Dict]) -> Dict[str, Any]:
                total_planned = sum(Decimal(str(s['planned'])) for s in subgroups)
                total_actual = sum(Decimal(str(s['actual'])) for s in subgroups)
                return {
                    'category': cat,
                    'name': name,
                    'total_planned': float(total_planned),
                    'total_actual': float(total_actual),
                    'project_count': sum(s['project_count'] for s in subgroups),
                    'progress': float(safe_divide(total_actual, total_planned, Decimal('100'))),
                    'subgroups': subgroups
                }

            project_dept_groups = [g for g in org_groups.values() if g['category'] == 'project_dept']
            dispatch_groups = [g for g in org_groups.values() if g['category'] == 'dispatch']
            hq_office_groups = [g for g in org_groups.values() if g['category'] == 'headquarters_office']

            by_org = [
                build_org_summary('project_dept', '项目部（一线）', project_dept_groups),
                {
                    'category': 'headquarters',
                    'name': '安装公司机关',
                    'total_planned': float(sum(Decimal(str(g['planned'])) for g in dispatch_groups + hq_office_groups)),
                    'total_actual': float(sum(Decimal(str(g['actual'])) for g in dispatch_groups + hq_office_groups)),
                    'project_count': sum(g['project_count'] for g in dispatch_groups + hq_office_groups),
                    'progress': float(safe_divide(
                        sum(Decimal(str(g['actual'])) for g in dispatch_groups + hq_office_groups),
                        sum(Decimal(str(g['planned'])) for g in dispatch_groups + hq_office_groups),
                        Decimal('100')
                    )),
                    'subgroups': [
                        {'sub_name': '派出机构', 'sub_category': 'dispatch', 'subgroups': dispatch_groups},
                        {'sub_name': '机关本部', 'sub_category': 'headquarters_office', 'subgroups': hq_office_groups}
                    ]
                }
            ]

            return jsonify({
                'year_month': year_month,
                'projects': result,
                'by_dept': list(org_groups.values()),
                'by_org': by_org
            }), 200
    except Exception:
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


# ============= 验收资料接口 =============

@bp.route('/api/acceptance-docs', methods=['GET'])
@login_required
def list_acceptance_docs(user: Dict[str, Any]) -> Tuple[Any, int]:
    """验收资料列表"""
    project_id = request.args.get('project_id', type=int)
    status = request.args.get('status', '')
    year_month = request.args.get('year_month', '')

    try:
        with get_db_cursor() as cur:
            conditions = ["1=1"]
            params: List[Any] = []
            if project_id:
                conditions.append("a.project_id=%s")
                params.append(project_id)
            if status:
                conditions.append("a.review_status=%s")
                params.append(status)
            if year_month:
                # 同样优化为范围查询
                start, end = get_month_range(year_month)
                conditions.append("a.uploaded_at >= %s AND a.uploaded_at < %s")
                params.extend([start, end])

            sql = f"""
                SELECT a.*, p.name AS project_name
                FROM acceptance_docs a
                LEFT JOIN projects p ON p.id = a.project_id
                WHERE {' AND '.join(conditions)}
                ORDER BY a.uploaded_at DESC
            """
            cur.execute(sql, params)
            docs = cur.fetchall()
            format_doc_dates(docs)
            return jsonify(docs), 200
    except Exception:
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/acceptance-docs', methods=['POST'])
@login_required
def upload_acceptance_doc(user: Dict[str, Any]) -> Tuple[Any, int]:
    """上传验收资料（任何登录用户）"""
    data = request.json or {}

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO acceptance_docs
                    (project_id, node_id, doc_type, doc_title, file_url, file_name,
                     uploaded_by, uploaded_by_name, output_value)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                data.get('project_id'),
                data.get('node_id'),
                data.get('doc_type', ''),
                data.get('doc_title', ''),
                data.get('file_url', ''),
                data.get('file_name', ''),
                user['phone'],
                user['name'],
                data.get('output_value', 0)
            ))
            did = cur.fetchone()['id']
            return jsonify({'success': True, 'id': did}), 200
    except Exception:
        return jsonify({'error': '上传失败，请稍后重试'}), 500


@bp.route('/api/acceptance-docs/<int:did>/review', methods=['POST'])
@login_required
@reviewer_required
def review_acceptance_doc(user: Dict[str, Any], did: int) -> Tuple[Any, int]:
    """审核验收资料（领导班子/超管）"""
    data = request.json or {}
    action = data.get('action')
    comment = data.get('comment', '')

    if action not in ('approve', 'reject'):
        return jsonify({'error': 'action必须是approve或reject'}), 400

    status = STATUS_APPROVED if action == 'approve' else STATUS_REJECTED

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE acceptance_docs SET
                    review_status=%s,
                    reviewed_by=%s,
                    reviewed_by_name=%s,
                    reviewed_at=NOW(),
                    review_comment=%s
                WHERE id=%s
            """, (status, user['phone'], user['name'], comment, did))
            return jsonify({'success': True}), 200
    except Exception:
        return jsonify({'error': '审核失败，请稍后重试'}), 500


# ============= 综合考核接口 =============

@bp.route('/api/assessment/my-score', methods=['GET'])
@login_required
def my_assessment_score(user: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """我的综合考核分（KPI + 产值 + 360评价）"""
    period = request.args.get('period', get_period_from_date())
    cycle_id = request.args.get('cycle_id', type=int)

    try:
        with get_db_cursor() as cur:
            me = get_my_person(cur, user['phone'])
            if not me:
                return jsonify({'error': '用户未找到'}), 404

            # 1. KPI分
            kpi_score = calculate_kpi_score(cur, me['name'], period)

            # 2. 产值分
            project_dept = me.get('project') or ''
            is_proj = is_project_department(project_dept)
            output_score = calculate_output_score(cur, project_dept, period) if is_proj else Decimal('0')

            # 3. 360评价分（按考核周期取）
            eval_score, eval_count = calculate_eval_score(cur, me['id'], cycle_id)
            actual_cycle_id = cycle_id or get_latest_closed_cycle_id(cur)
            cycle_info = get_cycle_info(cur, actual_cycle_id) if actual_cycle_id else None

            # 综合分
            final_score = calculate_final_score(kpi_score, output_score, eval_score, is_proj)

            return jsonify({
                'period': period,
                'cycle_id': actual_cycle_id,
                'cycle_name': cycle_info['name'] if cycle_info else '',
                'person': {
                    'id': me['id'],
                    'name': me['name'],
                    'dept': me.get('dept') or '',
                    'project': project_dept,
                    'position': me.get('position') or ''
                },
                'kpi_score': float(kpi_score),
                'output_score': float(output_score),
                'eval_score': float(eval_score),
                'eval_count': eval_count,
                'final_score': float(final_score),
                'is_project_dept': is_proj,
                'has_cycle': bool(cycle_info)
            }), 200
    except Exception:
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/assessment/team-score', methods=['GET'])
@login_required
@admin_required
def team_assessment_scores(user: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """团队综合考核分（管理员）"""
    period = request.args.get('period', get_period_from_date())
    cycle_id = request.args.get('cycle_id', type=int)
    level = request.args.get('level', 'all')

    # 人员层级过滤SQL条件（psycopg2 中 % 需转义为 %%）
    LEVEL_CONDITIONS = {
        'team': """AND category='正式职工' AND (
            position LIKE '%%经理%%' OR position LIKE '%%书记%%' OR
            position LIKE '%%部长%%' OR position LIKE '%%主任%%' OR
            position LIKE '%%负责人%%' OR position LIKE '%%主管%%' OR
            position LIKE '%%副%%'
        ) AND (is_external=false OR is_external IS NULL)""",
        'staff': """AND category='正式职工' AND (
            position NOT LIKE '%%经理%%' AND position NOT LIKE '%%书记%%' AND
            position NOT LIKE '%%部长%%' AND position NOT LIKE '%%主任%%' AND
            position NOT LIKE '%%负责人%%' AND position NOT LIKE '%%主管%%' AND
            position NOT LIKE '%%副%%'
        ) AND (is_external=false OR is_external IS NULL)""",
        'outsource': "AND category IN ('C1', 'C2') AND (is_external=false OR is_external IS NULL)",
        'external': "AND is_external=true",
    }
    level_condition = LEVEL_CONDITIONS.get(level, '')

    try:
        with get_db_cursor() as cur:
            sql = f"""
                SELECT id, name, dept, project, position, category, is_external
                FROM personnel
                WHERE (leave_date IS NULL OR leave_date='')
                  AND position NOT LIKE %s
                  AND position NOT LIKE %s
                  AND position NOT LIKE %s
                  {level_condition}
                ORDER BY project, dept, name
            """
            cur.execute(sql, POSITION_EXCLUDE_PATTERNS)
            personnel = cur.fetchall()

            actual_cycle_id = cycle_id or get_latest_closed_cycle_id(cur)
            cycle_info = get_cycle_info(cur, actual_cycle_id) if actual_cycle_id else None

            person_ids = [p['id'] for p in personnel]
            person_names = [p['name'] for p in personnel]

            # 批量 KPI 分（一次查询）
            kpi_map: Dict[str, Decimal] = {}
            if person_names:
                cur.execute("""
                    SELECT assignee,
                           COALESCE(SUM(weight), 0) AS tw,
                           COALESCE(SUM(CASE
                               WHEN status=%s OR COALESCE(progress,0)>=100 THEN weight*100
                               ELSE weight*COALESCE(progress,0)
                           END), 0) AS earned
                    FROM tasks
                    WHERE assignee = ANY(%s)
                      AND (kpi_period=%s OR (kpi_period='' AND TO_CHAR(created_at, 'YYYY-MM')=%s))
                    GROUP BY assignee
                """, (STATUS_COMPLETED, person_names, period, period))
                for r in cur.fetchall():
                    kpi_map[r['assignee']] = safe_divide(r['earned'], r['tw'])

            # 批量 360 评价分
            eval_map: Dict[Any, Tuple[Decimal, int]] = {}
            if person_ids and actual_cycle_id:
                cur.execute("""
                    SELECT evaluatee_id,
                           AVG(total_score) AS avg_score,
                           COUNT(*) AS cnt
                    FROM evaluation_scores
                    WHERE evaluatee_id = ANY(%s) AND cycle_id=%s
                    GROUP BY evaluatee_id
                """, (person_ids, actual_cycle_id))
                for r in cur.fetchall():
                    eval_map[r['evaluatee_id']] = (
                        to_decimal(r['avg_score']),
                        r['cnt'] or 0
                    )

            # 按部门预计算产值（一次查询，使用范围查询优化）
            start_date, end_date = get_month_range(period)
            cur.execute("""
                SELECT p.dept,
                       COALESCE(SUM(pl.planned_output), 0) AS planned,
                       COALESCE(SUM(CASE WHEN a.review_status=%s THEN a.output_value ELSE 0 END), 0) AS actual
                FROM projects p
                LEFT JOIN project_output_plans pl ON pl.project_id=p.id AND pl.year_month=%s
                LEFT JOIN acceptance_docs a ON a.project_id=p.id
                    AND a.uploaded_at >= %s AND a.uploaded_at < %s
                WHERE p.status=%s
                GROUP BY p.dept
            """, (STATUS_APPROVED, period, start_date, end_date, STATUS_ACTIVE))
            dept_output = {
                r['dept'] or '': float(safe_divide(r['actual'], r['planned'], Decimal('100')))
                for r in cur.fetchall()
            }

            result = []
            level_stats = {'team': 0, 'staff': 0, 'outsource': 0, 'external': 0}

            for p in personnel:
                # 1. KPI分
                kpi_score = kpi_map.get(p['name'], Decimal('0'))

                # 2. 产值分
                project_dept = p.get('project') or ''
                is_proj = is_project_department(project_dept)
                output_score = Decimal(str(dept_output.get(project_dept, 0))) if is_proj else Decimal('0')

                # 3. 360评价分
                eval_score, eval_count = eval_map.get(p['id'], (Decimal('0'), 0))

                # 综合分
                final_score = calculate_final_score(kpi_score, output_score, eval_score, is_proj)

                # 人员层级
                plevel = classify_person_level(
                    p.get('category') or '',
                    p.get('position') or '',
                    p.get('is_external') or False
                )
                level_stats[plevel] += 1

                result.append({
                    'id': p['id'],
                    'name': p['name'],
                    'dept': p.get('dept') or '',
                    'project': project_dept,
                    'position': p.get('position') or '',
                    'category': p.get('category') or '',
                    'is_external': p.get('is_external') or False,
                    'person_level': plevel,
                    'is_project_dept': is_proj,
                    'kpi_score': float(kpi_score),
                    'output_score': float(output_score),
                    'eval_score': float(eval_score),
                    'eval_count': eval_count,
                    'final_score': float(final_score)
                })

            result.sort(key=lambda x: x['final_score'], reverse=True)
            return jsonify({
                'period': period,
                'cycle_id': actual_cycle_id,
                'cycle_name': cycle_info['name'] if cycle_info else '',
                'level': level,
                'level_stats': level_stats,
                'scores': result
            }), 200
    except Exception:
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/assessment/cycles', methods=['GET'])
@login_required
def list_assessment_cycles(user: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """获取考核周期列表（综合考核用）"""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT id, name, period, status, start_date, end_date
                FROM evaluation_cycles
                ORDER BY id DESC
            """)
            cycles = cur.fetchall()
            return jsonify({'cycles': cycles or []}), 200
    except Exception:
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500
