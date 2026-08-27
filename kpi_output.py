"""KPI考核 + 产值看板 + 综合考核 API
Kim优化版（修复了multiply_by_100参数bug）
"""
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, Union

from flask import Blueprint, jsonify, request
from supabase_config import get_db

bp = Blueprint('kpi_output', __name__)
logger = logging.getLogger(__name__)

# ============= 常量配置 =============

# 权限相关
SUPER_ADMIN_PHONE: str = '18184005669'
PRODUCTION_ADMIN_PHONE: str = '15196251135'  # 周进 F14
LEADER_PHONES: Dict[str, str] = {
    '18523176628': '邱方恒',  # F4 经理
    '13980885726': '廖志成',  # F2 书记
    '17636671760': '吕亮',    # F1 副经理
    '18382194536': '李强',    # F3 商务经理
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


# ============= 数据库上下文管理器 =============

class DatabaseContext:
    """数据库连接上下文管理器，自动处理提交、回滚和关闭"""

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
                logger.error(f"数据库事务回滚: {exc_val}", exc_info=True)
            else:
                self.conn.commit()
            self.conn.close()
        return False


def get_db_cursor():
    """获取数据库游标的上下文管理器"""
    return DatabaseContext()


# ============= 权限装饰器 =============

def login_required(f):
    """登录校验装饰器，验证请求头中的X-User-Phone"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '未登录'}), 401
        return f(user, *args, **kwargs)
    return decorated


def admin_required(f):
    """管理员权限装饰器（超管+生产管理员+4领导班子）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '未登录'}), 401
        if not has_management_right(user['phone']):
            return jsonify({'error': '无权限'}), 403
        return f(user, *args, **kwargs)
    return decorated


def reviewer_required(f):
    """审核权限装饰器（超管+4领导班子）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '未登录'}), 401
        if not is_reviewer(user['phone']):
            return jsonify({'error': '无审核权限'}), 403
        return f(user, *args, **kwargs)
    return decorated


# ============= 基础工具函数 =============

def get_current_user() -> Optional[Dict[str, Any]]:
    """从请求头获取当前用户信息

    Returns:
        用户字典(phone, name, is_admin)或None
    """
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
    if user_phone == SUPER_ADMIN_PHONE:
        return True
    if user_phone == PRODUCTION_ADMIN_PHONE:
        return True
    if user_phone in LEADER_PHONES:
        return True
    return False


def is_reviewer(user_phone: str) -> bool:
    """是否有审核权限（超管+4领导班子）"""
    if user_phone == SUPER_ADMIN_PHONE:
        return True
    if user_phone in LEADER_PHONES:
        return True
    return False


def get_period_from_date(date_str: str = '') -> str:
    """从日期字符串获取YYYY-MM格式"""
    if not date_str:
        return datetime.now().strftime('%Y-%m')
    try:
        return datetime.strptime(date_str[:10], '%Y-%m-%d').strftime('%Y-%m')
    except Exception:
        return datetime.now().strftime('%Y-%m')


# ============= 核心计算函数 =============

def calculate_kpi_from_tasks(tasks: List[Dict[str, Any]]) -> Decimal:
    """根据任务列表计算KPI得分（0-100）

    公式：Σ(权重×进度) / Σ(权重)
    已完成任务按100分计算
    """
    total_weight = Decimal('0')
    earned = Decimal('0')
    for t in tasks:
        w = Decimal(str(t.get('weight') or DEFAULT_TASK_WEIGHT))
        total_weight += w
        prog = Decimal(str(t.get('progress') or 0))
        st = t.get('status') or ''
        if st == STATUS_COMPLETED or prog >= 100:
            earned += w * Decimal('100')
        else:
            earned += w * prog
    if total_weight > 0:
        return (earned / total_weight).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return Decimal('0')


def calculate_kpi_score(cur, assignee_name: str, period: str) -> Decimal:
    """从数据库查询并计算个人KPI得分（0-100）

    Args:
        cur: 数据库游标
        assignee_name: 任务执行人姓名
        period: 考核月份YYYY-MM

    Returns:
        KPI得分（Decimal，0-100）
    """
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
    total_w = Decimal(str(row['total_weight'] or 0))
    earned = Decimal(str(row['earned'] or 0))
    if total_w > 0:
        return (earned / total_w).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return Decimal('0')


def calculate_output_score(cur, dept: str, period: str) -> Decimal:
    """计算项目部产值完成率得分（0-100）

    公式：实际产值 / 计划产值 × 100
    """
    if not dept or dept in PROJECT_DEPT_EXCLUDE:
        return Decimal('0')
    cur.execute("""
        SELECT
            COALESCE(SUM(pl.planned_output), 0) AS planned,
            COALESCE(SUM(CASE WHEN a.review_status=%s THEN a.output_value ELSE 0 END), 0) AS actual
        FROM projects p
        LEFT JOIN project_output_plans pl ON pl.project_id=p.id AND pl.year_month=%s
        LEFT JOIN acceptance_docs a ON a.project_id=p.id
            AND TO_CHAR(a.uploaded_at, 'YYYY-MM')=%s
        WHERE p.dept=%s AND p.status=%s
    """, (STATUS_APPROVED, period, period, dept, STATUS_ACTIVE))
    row = cur.fetchone()
    planned = Decimal(str(row['planned'] or 0))
    actual = Decimal(str(row['actual'] or 0))
    if planned > 0:
        return (actual / planned * Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return Decimal('0')


def calculate_eval_score(cur, person_id: Union[int, str], cycle_id: Optional[int] = None) -> Tuple[Decimal, int]:
    """计算360评价平均分（指定周期内的）

    Args:
        cur: 数据库游标
        person_id: 被评价人ID
        cycle_id: 考核周期ID，None则取最近已关闭周期

    Returns:
        (平均分Decimal, 评价人数)
    """
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
    return Decimal(str(avg)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), cnt


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
    """计算综合考核分

    后台员工：KPI 60% + 360评价 40%
    项目部员工：产值 60% + 360评价 40%
    """
    if is_project_dept:
        final = output_score * OUTPUT_WEIGHT_RATIO + eval_score * EVAL_WEIGHT_RATIO
    else:
        final = kpi_score * KPI_WEIGHT_RATIO + eval_score * EVAL_WEIGHT_RATIO
    return final.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def is_project_department(project: Optional[str]) -> bool:
    """判断是否为项目部（非后台/未分配）"""
    return bool(project and project not in PROJECT_DEPT_EXCLUDE)


# ============= 格式化工具 =============

def format_datetime(dt: Any) -> str:
    """格式化日期时间为字符串"""
    return str(dt) if dt else ''


def format_task_dates(tasks: List[Dict[str, Any]]) -> None:
    """格式化任务列表中的日期和权重字段（原地修改）"""
    for t in tasks:
        t['created_at'] = format_datetime(t.get('created_at'))
        t['updated_at'] = format_datetime(t.get('updated_at'))
        t['weight'] = float(Decimal(str(t.get('weight') or DEFAULT_TASK_WEIGHT)))


def format_doc_dates(docs: List[Dict[str, Any]]) -> None:
    """格式化验收资料日期字段（原地修改）"""
    for d in docs:
        d['uploaded_at'] = format_datetime(d.get('uploaded_at'))
        d['reviewed_at'] = format_datetime(d.get('reviewed_at'))


# ============= KPI 接口 =============

@bp.route('/api/kpi/my-tasks', methods=['GET'])
@login_required
def kpi_my_tasks(user: Dict[str, Any]) -> Tuple[Any, int]:
    """当前用户某月KPI任务列表（含分数）

    Query Params:
        period (str): 考核月份YYYY-MM，默认当前月
    """
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
                Decimal(str(t.get('weight') or DEFAULT_TASK_WEIGHT)) for t in tasks
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
    except Exception as e:
        logger.error(f"获取个人KPI任务失败: {e}", exc_info=True)
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/kpi/team-summary', methods=['GET'])
@admin_required
def kpi_team_summary(user: Dict[str, Any]) -> Tuple[Any, int]:
    """团队某月KPI汇总（管理员可见）

    Query Params:
        period (str): 考核月份YYYY-MM，默认当前月
    """
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
                WHERE (p.leave_date IS NULL OR p.leave_date='')
                  AND p.position NOT LIKE %s
                  AND p.position NOT LIKE %s
                  AND p.position NOT LIKE %s
                GROUP BY p.id, p.name, p.dept, p.project, p.position
                ORDER BY earned DESC NULLS LAST
            """, (
                STATUS_COMPLETED, period, period,
                POSITION_EXCLUDE_PATTERNS[0],
                POSITION_EXCLUDE_PATTERNS[1],
                POSITION_EXCLUDE_PATTERNS[2]
            ))
            rows = cur.fetchall()

            result = []
            for r in rows:
                total_w = Decimal(str(r.get('total_weight') or 0))
                earned = Decimal(str(r.get('earned') or 0))
                if total_w > 0:
                    score = (earned / total_w).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                else:
                    score = Decimal('0')

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
    except Exception as e:
        logger.error(f"获取团队KPI汇总失败: {e}", exc_info=True)
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/kpi/update-source', methods=['POST'])
@login_required
def update_task_kpi_source(user: Dict[str, Any]) -> Tuple[Any, int]:
    """更新任务的KPI来源（任务发布时自动调用）

    Body:
        task_id (int): 任务ID
        source (str): 来源类型，默认'manual'
        weight (int): 权重值
        kpi_period (str): 考核月份YYYY-MM
    """
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
    except Exception as e:
        logger.error(f"更新任务KPI来源失败: {e}", exc_info=True)
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
    except Exception as e:
        logger.error(f"获取项目列表失败: {e}", exc_info=True)
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/projects', methods=['POST'])
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
    except Exception as e:
        logger.error(f"创建项目失败: {e}", exc_info=True)
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
    except Exception as e:
        logger.error(f"获取项目详情失败: {e}", exc_info=True)
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/projects/<int:pid>/nodes', methods=['POST'])
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
    except Exception as e:
        logger.error(f"添加项目节点失败: {e}", exc_info=True)
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
    except Exception as e:
        logger.error(f"更新节点失败: {e}", exc_info=True)
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
    except Exception as e:
        logger.error(f"获取产值计划失败: {e}", exc_info=True)
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/output/plans', methods=['POST'])
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
    except Exception as e:
        logger.error(f"更新产值计划失败: {e}", exc_info=True)
        return jsonify({'error': '更新失败，请稍后重试'}), 500


@bp.route('/api/output/dashboard', methods=['GET'])
@login_required
def output_dashboard(user: Dict[str, Any]) -> Tuple[Any, int]:
    """产值看板：所有项目部本月完成情况"""
    year_month = request.args.get('year_month', get_period_from_date())

    try:
        with get_db_cursor() as cur:
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
                    AND TO_CHAR(a.uploaded_at, 'YYYY-MM') = %s
                WHERE p.status = %s
                GROUP BY p.id, p.name, p.dept, p.total_contract_value, per.name, pl.planned_output
                ORDER BY p.dept, p.name
            """, (STATUS_APPROVED, STATUS_PENDING, year_month, year_month, STATUS_ACTIVE))
            projects = cur.fetchall()

            result = []
            for p in projects:
                planned = Decimal(str(p.get('planned_output') or 0))
                actual = Decimal(str(p.get('actual_output') or 0))
                progress = (actual / planned * Decimal('100')).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                ) if planned > 0 else Decimal('0')

                result.append({
                    'id': p['id'],
                    'name': p['name'],
                    'dept': p.get('dept') or '',
                    'total_contract_value': float(Decimal(str(p.get('total_contract_value') or 0))),
                    'manager_name': p.get('manager_name') or '',
                    'planned_output': float(planned),
                    'actual_output': float(actual),
                    'progress': float(progress),
                    'pending_docs': p.get('pending_docs') or 0
                })

            by_dept: Dict[str, Dict[str, Any]] = {}
            for r in result:
                d = r['dept'] or '未分配'
                if d not in by_dept:
                    by_dept[d] = {
                        'dept': d,
                        'project_count': 0,
                        'planned': Decimal('0'),
                        'actual': Decimal('0'),
                        'projects': []
                    }
                by_dept[d]['project_count'] += 1
                by_dept[d]['planned'] += Decimal(str(r['planned_output']))
                by_dept[d]['actual'] += Decimal(str(r['actual_output']))
                by_dept[d]['projects'].append(r)

            dept_list = []
            for d in by_dept.values():
                dept_progress = (d['actual'] / d['planned'] * Decimal('100')).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                ) if d['planned'] > 0 else Decimal('0')
                dept_list.append({
                    'dept': d['dept'],
                    'project_count': d['project_count'],
                    'planned': float(d['planned']),
                    'actual': float(d['actual']),
                    'progress': float(dept_progress),
                    'projects': d['projects']
                })

            return jsonify({
                'year_month': year_month,
                'projects': result,
                'by_dept': dept_list
            }), 200
    except Exception as e:
        logger.error(f"获取产值看板失败: {e}", exc_info=True)
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


# ============= 验收资料接口 =============

@bp.route('/api/acceptance-docs', methods=['GET'])
@login_required
def list_acceptance_docs(user: Dict[str, Any]) -> Tuple[Any, int]:
    """验收资料列表

    Query Params:
        project_id (int): 项目ID
        status (str): 审核状态（pending/approved/rejected）
        year_month (str): 上传月份YYYY-MM
    """
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
                conditions.append("TO_CHAR(a.uploaded_at, 'YYYY-MM')=%s")
                params.append(year_month)

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
    except Exception as e:
        logger.error(f"获取验收资料失败: {e}", exc_info=True)
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
    except Exception as e:
        logger.error(f"上传验收资料失败: {e}", exc_info=True)
        return jsonify({'error': '上传失败，请稍后重试'}), 500


@bp.route('/api/acceptance-docs/<int:did>/review', methods=['POST'])
@reviewer_required
def review_acceptance_doc(user: Dict[str, Any], did: int) -> Tuple[Any, int]:
    """审核验收资料（领导班子/超管）

    Body:
        action (str): 'approve'或'reject'
        comment (str): 审核意见
    """
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
    except Exception as e:
        logger.error(f"审核验收资料失败: {e}", exc_info=True)
        return jsonify({'error': '审核失败，请稍后重试'}), 500


# ============= 综合考核接口 =============

@bp.route('/api/assessment/my-score', methods=['GET'])
@login_required
def my_assessment_score(user: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """我的综合考核分（KPI + 产值 + 360评价）

    360评价按考核周期取分：
    - 指定 cycle_id：用该周期的评价分
    - 未指定：自动取最近已关闭的考核周期

    考核周期关闭后，分数自动可用（无需手动同步）。

    后台员工：任务KPI 60% + 360评价 40%
    项目部员工：产值 60% + 360评价 40%
    """
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
    except Exception as e:
        logger.error(f"获取个人综合考核分失败: {e}", exc_info=True)
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/assessment/team-score', methods=['GET'])
@admin_required
def team_assessment_scores(user: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """团队综合考核分（管理员）

    计算所有在职非辅助人员的综合考核分，按得分降序。
    360评价按指定周期取分（未指定则用最近已关闭周期）。

    Query Params:
        period (str): 考核月份
        cycle_id (int): 考核周期ID（可选）
        level (str): 人员层级过滤
            - 'team'      团队（副部长及以上：经理/书记/部长/主任/负责人/主管/副*）
            - 'staff'     普通职工（正式职工中除管理层之外）
            - 'outsource' 外包人员（C1+C2）
            - 'external'  外协人员（is_external=true）
            - 'all' 或不传 全部（包含正式职工+外包+外协）

    说明：正式职工 = 团队 + 普通职工（管理层 + 非管理层）

    后台员工：任务KPI 60% + 360评价 40%
    项目部员工：产值 60% + 360评价 40%
    """
    period = request.args.get('period', get_period_from_date())
    cycle_id = request.args.get('cycle_id', type=int)
    level = request.args.get('level', 'all')

    # 人员层级过滤SQL条件
    # psycopg2 用 %s 占位符时，SQL 中的字面量 % 必须转义为 %%
    if level == 'team':
        level_condition = """AND category='正式职工' AND (
            position LIKE '%%经理%%' OR position LIKE '%%书记%%' OR
            position LIKE '%%部长%%' OR position LIKE '%%主任%%' OR
            position LIKE '%%负责人%%' OR position LIKE '%%主管%%' OR
            position LIKE '%%副%%'
        ) AND (is_external=false OR is_external IS NULL)"""
    elif level == 'staff':
        level_condition = """AND category='正式职工' AND (
            position NOT LIKE '%%经理%%' AND position NOT LIKE '%%书记%%' AND
            position NOT LIKE '%%部长%%' AND position NOT LIKE '%%主任%%' AND
            position NOT LIKE '%%负责人%%' AND position NOT LIKE '%%主管%%' AND
            position NOT LIKE '%%副%%'
        ) AND (is_external=false OR is_external IS NULL)"""
    elif level == 'outsource':
        level_condition = "AND category IN ('C1', 'C2')"
    elif level == 'external':
        level_condition = "AND is_external=true"
    else:
        level_condition = ""

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

            # 按层级分组统计
            level_stats = {'team': 0, 'staff': 0, 'outsource': 0, 'external': 0}

            # 批量查询：避免 N+1 查询（每个 person 多次查询）
            person_ids = [p['id'] for p in personnel]
            person_names = [p['name'] for p in personnel]

            # 批量 KPI 分（一次查询）
            kpi_map = {}
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
                    tw = Decimal(str(r['tw'] or 0))
                    earned = Decimal(str(r['earned'] or 0))
                    kpi_map[r['assignee']] = (earned / tw).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if tw > 0 else Decimal('0')

            # 批量 360 评价分（按周期过滤）
            eval_map = {}
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
                    avg = r['avg_score'] or 0
                    eval_map[r['evaluatee_id']] = (
                        Decimal(str(avg)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
                        r['cnt'] or 0
                    )

            # 按部门预计算产值（一次查询）
            cur.execute("""
                SELECT p.dept,
                       COALESCE(SUM(pl.planned_output), 0) AS planned,
                       COALESCE(SUM(CASE WHEN a.review_status=%s THEN a.output_value ELSE 0 END), 0) AS actual
                FROM projects p
                LEFT JOIN project_output_plans pl ON pl.project_id=p.id AND pl.year_month=%s
                LEFT JOIN acceptance_docs a ON a.project_id=p.id
                    AND TO_CHAR(a.uploaded_at, 'YYYY-MM')=%s
                WHERE p.status=%s
                GROUP BY p.dept
            """, (STATUS_APPROVED, period, period, STATUS_ACTIVE))
            dept_output = {}
            for r in cur.fetchall():
                planned = Decimal(str(r['planned'] or 0))
                actual = Decimal(str(r['actual'] or 0))
                score = (actual / planned * Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if planned > 0 else Decimal('0')
                dept_output[r['dept'] or ''] = float(score)

            result = []
            for p in personnel:
                # 1. KPI分（从批量结果取）
                kpi_score = kpi_map.get(p['name'], Decimal('0'))

                # 2. 产值分（按部门从预计算结果取）
                project_dept = p.get('project') or ''
                is_proj = is_project_department(project_dept)
                output_score = Decimal(str(dept_output.get(project_dept, 0))) if is_proj else Decimal('0')

                # 3. 360评价分（从批量结果取）
                eval_score, eval_count = eval_map.get(p['id'], (Decimal('0'), 0))

                final_score = calculate_final_score(kpi_score, output_score, eval_score, is_proj)

                # 人员层级归类
                cat = p.get('category') or ''
                is_ext = p.get('is_external') or False
                pos = p.get('position') or ''

                # 团队判定：position 包含副/经理/书记/部长/主任/负责人/主管
                is_management = (
                    ('副' in pos) or ('经理' in pos) or ('书记' in pos) or
                    ('部长' in pos) or ('主任' in pos) or ('负责人' in pos) or ('主管' in pos)
                )

                if is_ext:
                    plevel = 'external'
                elif cat in ('C1', 'C2'):
                    plevel = 'outsource'
                elif cat == '正式职工' and is_management:
                    plevel = 'team'
                else:
                    plevel = 'staff'
                level_stats[plevel] += 1

                result.append({
                    'id': p['id'],
                    'name': p['name'],
                    'dept': p.get('dept') or '',
                    'project': project_dept,
                    'position': pos,
                    'category': cat,
                    'is_external': is_ext,
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
    except Exception as e:
        logger.error(f"获取团队综合考核分失败: {e}", exc_info=True)
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500


@bp.route('/api/assessment/cycles', methods=['GET'])
@login_required
def list_assessment_cycles(user: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """获取考核周期列表（综合考核用）

    返回已关闭的周期列表（按ID倒序）和当前活跃周期。
    """
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT id, name, period, status, start_date, end_date
                FROM evaluation_cycles
                ORDER BY id DESC
            """)
            cycles = cur.fetchall()
            return jsonify({'cycles': cycles or []}), 200
    except Exception as e:
        logger.error(f"获取考核周期列表失败: {e}", exc_info=True)
        return jsonify({'error': '获取数据失败，请稍后重试'}), 500
