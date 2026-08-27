"""KPI考核 + 产值看板 + 综合考核 API"""
from flask import Blueprint, request, jsonify
from supabase_config import get_db
from psycopg2.extras import RealDictCursor
from datetime import datetime
from decimal import Decimal

bp = Blueprint('kpi_output', __name__)

# ============= 权限管理 =============

SUPER_ADMIN_PHONE = '18184005669'
PRODUCTION_ADMIN_PHONE = '15196251135'  # 周进 F14
LEADER_PHONES = {
    '18523176628': '邱方恒',  # F4 经理
    '13980885726': '廖志成',  # F2 书记
    '17636671760': '吕亮',    # F1 副经理
    '18382194536': '李强',    # F3 商务经理
}

def get_current_user():
    """从请求头获取当前用户"""
    phone = request.headers.get('X-User-Phone', '')
    if not phone:
        return None
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT phone, name, is_admin FROM users WHERE phone=%s", (phone,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

def get_my_person(cur, phone):
    """获取当前用户的personnel信息"""
    cur.execute("SELECT * FROM personnel WHERE phone=%s", (phone,))
    return cur.fetchone()

def has_management_right(user_phone, name=''):
    """是否有管理权限（超管+周进+4领导班子）"""
    if user_phone == SUPER_ADMIN_PHONE:
        return True
    if user_phone == PRODUCTION_ADMIN_PHONE:
        return True
    if user_phone in LEADER_PHONES:
        return True
    return False

def is_reviewer(user_phone):
    """是否有审核权限（超管+4领导班子）"""
    if user_phone == SUPER_ADMIN_PHONE:
        return True
    if user_phone in LEADER_PHONES:
        return True
    return False

def get_period_from_date(date_str=''):
    """从日期获取YYYY-MM"""
    if not date_str:
        return datetime.now().strftime('%Y-%m')
    try:
        return datetime.strptime(date_str[:10], '%Y-%m-%d').strftime('%Y-%m')
    except Exception:
        return datetime.now().strftime('%Y-%m')

# ============= KPI 计算 =============

@bp.route('/api/kpi/my-tasks', methods=['GET'])
def kpi_my_tasks():
    """当前用户某月KPI任务列表（含分数）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    period = request.args.get('period', get_period_from_date())

    conn = get_db()
    cur = conn.cursor()
    me = get_my_person(cur, user['phone'])
    if not me:
        cur.close(); conn.close()
        return jsonify({'tasks': [], 'kpi_score': 0, 'period': period})

    # 查本人当月任务（自动算出KPI期属于当月的）
    cur.execute("""
        SELECT id, title, content, status, progress, weight, source, deadline,
               created_at, updated_at, publisher_name, kpi_period
        FROM tasks
        WHERE assignee=%s
          AND (kpi_period=%s OR (kpi_period='' AND TO_CHAR(created_at, 'YYYY-MM')=%s))
        ORDER BY created_at DESC
    """, (me['name'], period, period))
    tasks = cur.fetchall()

    # 计算KPI分：Σ(完成度 × 权重) / Σ权重 × 100
    total_weight = Decimal('0')
    earned = Decimal('0')
    for t in tasks:
        w = Decimal(str(t.get('weight') or 10))
        total_weight += w
        prog = Decimal(str(t.get('progress') or 0))
        st = t.get('status') or ''
        # 已完成 = 100, 进行中按progress, 其他 = 0
        if st == '已完成' or prog >= 100:
            earned += w * 100
        else:
            earned += w * prog

    kpi_score = float(earned / total_weight) if total_weight > 0 else 0
    kpi_score = round(kpi_score, 2)

    for t in tasks:
        t['created_at'] = str(t['created_at']) if t.get('created_at') else ''
        t['updated_at'] = str(t['updated_at']) if t.get('updated_at') else ''
        t['weight'] = float(t.get('weight') or 10)

    cur.close(); conn.close()
    return jsonify({
        'tasks': tasks,
        'kpi_score': kpi_score,
        'period': period,
        'task_count': len(tasks),
        'total_weight': float(total_weight),
        'completed_count': sum(1 for t in tasks if (t.get('status') == '已完成' or (t.get('progress') or 0) >= 100))
    })


@bp.route('/api/kpi/team-summary', methods=['GET'])
def kpi_team_summary():
    """团队某月KPI汇总（管理员可见）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    if not has_management_right(user['phone']):
        return jsonify({'error': '无权限'}), 403

    period = request.args.get('period', get_period_from_date())

    conn = get_db()
    cur = conn.cursor()

    # 查所有在岗人员的当月KPI
    cur.execute("""
        SELECT p.id, p.name, p.dept, p.project, p.position,
               COUNT(t.id) AS task_count,
               COALESCE(SUM(t.weight), 0) AS total_weight,
               COALESCE(SUM(CASE
                   WHEN t.status='已完成' OR COALESCE(t.progress,0)>=100 THEN t.weight*100
                   ELSE t.weight*COALESCE(t.progress,0)
               END), 0) AS earned
        FROM personnel p
        LEFT JOIN tasks t ON t.assignee=p.name
            AND (t.kpi_period=%s OR (t.kpi_period='' AND TO_CHAR(t.created_at, 'YYYY-MM')=%s))
        WHERE (p.leave_date IS NULL OR p.leave_date='')
          AND p.position NOT LIKE '%%司机%%'
          AND p.position NOT LIKE '%%实习%%'
          AND p.position NOT LIKE '%%见习%%'
        GROUP BY p.id, p.name, p.dept, p.project, p.position
        ORDER BY earned DESC NULLS LAST
    """, (period, period))
    rows = cur.fetchall()

    result = []
    for r in rows:
        total_w = float(r.get('total_weight') or 0)
        earned = float(r.get('earned') or 0)
        score = round(earned / total_w, 2) if total_w > 0 else 0
        result.append({
            'id': r['id'],
            'name': r['name'],
            'dept': r.get('dept') or '',
            'project': r.get('project') or '',
            'position': r.get('position') or '',
            'task_count': r.get('task_count') or 0,
            'kpi_score': score
        })

    cur.close(); conn.close()
    return jsonify({'period': period, 'summary': result})


@bp.route('/api/kpi/update-source', methods=['POST'])
def update_task_kpi_source():
    """更新任务的KPI来源（任务发布时自动调用）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401

    data = request.json
    task_id = data.get('task_id')
    source = data.get('source', 'manual')  # weekly_meeting/leadership/manual
    weight = data.get('weight', 10)
    kpi_period = data.get('kpi_period', get_period_from_date())

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE tasks SET source=%s, weight=%s, kpi_period=%s
        WHERE id=%s
    """, (source, weight, kpi_period, task_id))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'success': True})


# ============= 项目管理 =============

@bp.route('/api/projects', methods=['GET'])
def list_projects():
    """项目列表"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.*, per.name AS manager_name
        FROM projects p
        LEFT JOIN personnel per ON per.id=p.manager_id
        ORDER BY p.id DESC
    """)
    projects = cur.fetchall()
    for p in projects:
        p['created_at'] = str(p['created_at']) if p.get('created_at') else ''
    cur.close(); conn.close()
    return jsonify(projects)


@bp.route('/api/projects', methods=['POST'])
def create_project():
    """新建项目（仅管理员）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    if not has_management_right(user['phone']):
        return jsonify({'error': '无权限'}), 403

    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO projects (name, dept, manager_id, manager_phone, total_contract_value, start_date, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
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
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'success': True, 'id': pid})


@bp.route('/api/projects/<int:pid>', methods=['GET'])
def get_project(pid):
    """项目详情（含节点、计划、产值）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.*, per.name AS manager_name
        FROM projects p
        LEFT JOIN personnel per ON per.id=p.manager_id
        WHERE p.id=%s
    """, (pid,))
    project = cur.fetchone()
    if not project:
        cur.close(); conn.close()
        return jsonify({'error': '项目不存在'}), 404

    project['created_at'] = str(project['created_at']) if project.get('created_at') else ''

    cur.execute("SELECT * FROM project_nodes WHERE project_id=%s ORDER BY id", (pid,))
    nodes = cur.fetchall()
    for n in nodes:
        n['created_at'] = str(n['created_at']) if n.get('created_at') else ''
    project['nodes'] = nodes

    cur.execute("SELECT * FROM project_output_plans WHERE project_id=%s ORDER BY year_month DESC", (pid,))
    plans = cur.fetchall()
    project['plans'] = plans

    cur.close(); conn.close()
    return jsonify(project)


@bp.route('/api/projects/<int:pid>/nodes', methods=['POST'])
def add_node(pid):
    """添加节点（仅管理员）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    if not has_management_right(user['phone']):
        return jsonify({'error': '无权限'}), 403

    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO project_nodes (project_id, node_name, planned_date, planned_output, weight)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (
        pid,
        data.get('node_name', ''),
        data.get('planned_date', ''),
        data.get('planned_output', 0),
        data.get('weight', 10)
    ))
    nid = cur.fetchone()['id']
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'success': True, 'id': nid})


@bp.route('/api/projects/<int:pid>/nodes/<int:nid>', methods=['PUT'])
def update_node(pid, nid):
    """更新节点"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401

    data = request.json
    conn = get_db()
    cur = conn.cursor()

    updates = []
    params = []
    for f in ['node_name', 'planned_date', 'actual_date', 'planned_output', 'status', 'weight']:
        if f in data:
            updates.append(f + '=%s')
            params.append(data[f])

    if updates:
        params.extend([nid, pid])
        cur.execute(f"UPDATE project_nodes SET {', '.join(updates)} WHERE id=%s AND project_id=%s", params)
        conn.commit()

    cur.close(); conn.close()
    return jsonify({'success': True})


# ============= 产值计划/实际 =============

@bp.route('/api/output/plans', methods=['GET'])
def get_output_plan():
    """获取某项目某月计划"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401

    project_id = request.args.get('project_id', type=int)
    year_month = request.args.get('year_month', get_period_from_date())
    if not project_id:
        return jsonify({'error': '缺少project_id'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM project_output_plans WHERE project_id=%s AND year_month=%s",
                (project_id, year_month))
    plan = cur.fetchone()
    cur.close(); conn.close()
    return jsonify(plan or {})


@bp.route('/api/output/plans', methods=['POST'])
def upsert_output_plan():
    """创建/更新产值计划（仅管理员）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    if not has_management_right(user['phone']):
        return jsonify({'error': '无权限'}), 403

    data = request.json
    project_id = data.get('project_id')
    year_month = data.get('year_month')
    planned_output = data.get('planned_output', 0)
    notes = data.get('notes', '')

    if not project_id or not year_month:
        return jsonify({'error': '缺少project_id或year_month'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO project_output_plans (project_id, year_month, planned_output, notes, created_by, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (project_id, year_month)
        DO UPDATE SET planned_output=EXCLUDED.planned_output,
                      notes=EXCLUDED.notes,
                      updated_at=NOW()
    """, (project_id, year_month, planned_output, notes, user['phone']))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'success': True})


@bp.route('/api/output/dashboard', methods=['GET'])
def output_dashboard():
    """产值看板：所有项目部本月完成情况"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401

    year_month = request.args.get('year_month', get_period_from_date())

    conn = get_db()
    cur = conn.cursor()

    # 查所有项目 + 计划 + 累计产值（来自已审核通过的验收资料）
    cur.execute("""
        SELECT
            p.id, p.name, p.dept, p.total_contract_value, per.name AS manager_name,
            pl.planned_output,
            COALESCE(SUM(CASE WHEN a.review_status='approved' THEN a.output_value ELSE 0 END), 0) AS actual_output,
            COUNT(CASE WHEN a.review_status='pending' THEN 1 END) AS pending_docs
        FROM projects p
        LEFT JOIN personnel per ON per.id = p.manager_id
        LEFT JOIN project_output_plans pl ON pl.project_id = p.id AND pl.year_month = %s
        LEFT JOIN acceptance_docs a ON a.project_id = p.id
            AND TO_CHAR(a.uploaded_at, 'YYYY-MM') = %s
        WHERE p.status = 'active'
        GROUP BY p.id, p.name, p.dept, p.total_contract_value, per.name, pl.planned_output
        ORDER BY p.dept, p.name
    """, (year_month, year_month))
    projects = cur.fetchall()

    result = []
    for p in projects:
        planned = float(p.get('planned_output') or 0)
        actual = float(p.get('actual_output') or 0)
        progress = round(actual / planned * 100, 2) if planned > 0 else 0
        result.append({
            'id': p['id'],
            'name': p['name'],
            'dept': p.get('dept') or '',
            'total_contract_value': float(p.get('total_contract_value') or 0),
            'manager_name': p.get('manager_name') or '',
            'planned_output': planned,
            'actual_output': actual,
            'progress': progress,
            'pending_docs': p.get('pending_docs') or 0
        })

    # 按项目部分组汇总
    by_dept = {}
    for r in result:
        d = r['dept'] or '未分配'
        if d not in by_dept:
            by_dept[d] = {'dept': d, 'project_count': 0, 'planned': 0, 'actual': 0, 'projects': []}
        by_dept[d]['project_count'] += 1
        by_dept[d]['planned'] += r['planned_output']
        by_dept[d]['actual'] += r['actual_output']
        by_dept[d]['projects'].append(r)

    for d in by_dept.values():
        d['progress'] = round(d['actual'] / d['planned'] * 100, 2) if d['planned'] > 0 else 0

    cur.close(); conn.close()
    return jsonify({
        'year_month': year_month,
        'projects': result,
        'by_dept': list(by_dept.values())
    })


# ============= 验收资料 =============

@bp.route('/api/acceptance-docs', methods=['GET'])
def list_acceptance_docs():
    """验收资料列表"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401

    project_id = request.args.get('project_id', type=int)
    status = request.args.get('status', '')
    year_month = request.args.get('year_month', '')

    conn = get_db()
    cur = conn.cursor()
    sql = """
        SELECT a.*, p.name AS project_name
        FROM acceptance_docs a
        LEFT JOIN projects p ON p.id = a.project_id
        WHERE 1=1
    """
    params = []
    if project_id:
        sql += " AND a.project_id=%s"
        params.append(project_id)
    if status:
        sql += " AND a.review_status=%s"
        params.append(status)
    if year_month:
        sql += " AND TO_CHAR(a.uploaded_at, 'YYYY-MM')=%s"
        params.append(year_month)
    sql += " ORDER BY a.uploaded_at DESC"
    cur.execute(sql, params)
    docs = cur.fetchall()
    for d in docs:
        for k in ['uploaded_at', 'reviewed_at']:
            d[k] = str(d[k]) if d.get(k) else ''
    cur.close(); conn.close()
    return jsonify(docs)


@bp.route('/api/acceptance-docs', methods=['POST'])
def upload_acceptance_doc():
    """上传验收资料（任何登录用户）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401

    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO acceptance_docs (project_id, node_id, doc_type, doc_title,
            file_url, file_name, uploaded_by, uploaded_by_name, output_value)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
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
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'success': True, 'id': did})


@bp.route('/api/acceptance-docs/<int:did>/review', methods=['POST'])
def review_acceptance_doc(did):
    """审核验收资料（领导班子）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    if not is_reviewer(user['phone']):
        return jsonify({'error': '无审核权限'}), 403

    data = request.json
    action = data.get('action')  # 'approve' or 'reject'
    comment = data.get('comment', '')

    if action not in ('approve', 'reject'):
        return jsonify({'error': 'action必须是approve或reject'}), 400

    status = 'approved' if action == 'approve' else 'rejected'
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE acceptance_docs SET
            review_status=%s,
            reviewed_by=%s,
            reviewed_by_name=%s,
            reviewed_at=NOW(),
            review_comment=%s
        WHERE id=%s
    """, (status, user['phone'], user['name'], comment, did))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'success': True})


# ============= 综合考核 =============

@bp.route('/api/assessment/my-score', methods=['GET'])
def my_assessment_score():
    """我的综合考核分（KPI + 产值 + 360评价）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401

    period = request.args.get('period', get_period_from_date())

    conn = get_db()
    cur = conn.cursor()
    me = get_my_person(cur, user['phone'])
    if not me:
        cur.close(); conn.close()
        return jsonify({'error': '用户未找到'}), 404

    # 1. KPI 分
    cur.execute("""
        SELECT
            COALESCE(SUM(weight), 0) AS total_weight,
            COALESCE(SUM(CASE
                WHEN status='已完成' OR COALESCE(progress,0)>=100 THEN weight*100
                ELSE weight*COALESCE(progress,0)
            END), 0) AS earned
        FROM tasks
        WHERE assignee=%s
          AND (kpi_period=%s OR (kpi_period='' AND TO_CHAR(created_at, 'YYYY-MM')=%s))
    """, (me['name'], period, period))
    kpi_row = cur.fetchone()
    kpi_score = round(float(kpi_row['earned']) / float(kpi_row['total_weight']) * 100, 2) \
                if float(kpi_row['total_weight']) > 0 else 0

    # 2. 产值分（项目部员工）
    output_score = 0
    is_project_dept = False
    project_dept = me.get('project') or ''
    if project_dept and project_dept != '后台' and project_dept != '未分配':
        is_project_dept = True
        # 取个人所在项目部所有项目的产值完成率
        cur.execute("""
            SELECT
                COALESCE(SUM(pl.planned_output), 0) AS planned,
                COALESCE(SUM(CASE WHEN a.review_status='approved' THEN a.output_value ELSE 0 END), 0) AS actual
            FROM projects p
            LEFT JOIN project_output_plans pl ON pl.project_id=p.id AND pl.year_month=%s
            LEFT JOIN acceptance_docs a ON a.project_id=p.id
                AND TO_CHAR(a.uploaded_at, 'YYYY-MM')=%s
            WHERE p.dept=%s AND p.status='active'
        """, (period, period, project_dept))
        out_row = cur.fetchone()
        planned = float(out_row['planned'] or 0)
        actual = float(out_row['actual'] or 0)
        output_score = round(actual / planned * 100, 2) if planned > 0 else 0

    # 3. 360评价分（取最近一个已关闭周期的综合分；若没有则取所有打分的平均）
    cur.execute("""
        SELECT AVG(total_score) AS avg_score, COUNT(*) AS cnt
        FROM evaluation_scores
        WHERE evaluatee_id=%s
    """, (me['id'],))
    eval_row = cur.fetchone()
    eval_score = round(float(eval_row['avg_score'] or 0), 2)

    # 综合分
    # 后台员工：任务KPI 60% + 360评价 40%
    # 项目部员工：产值 60% + 360评价 40%（产值本身就是项目部KPI）
    if is_project_dept:
        final_score = round(output_score * 0.6 + eval_score * 0.4, 2)
    else:
        final_score = round(kpi_score * 0.6 + eval_score * 0.4, 2)

    cur.close(); conn.close()
    return jsonify({
        'period': period,
        'person': {
            'id': me['id'],
            'name': me['name'],
            'dept': me.get('dept') or '',
            'project': me.get('project') or '',
            'position': me.get('position') or ''
        },
        'kpi_score': kpi_score,
        'output_score': output_score,
        'eval_score': eval_score,
        'final_score': final_score,
        'is_project_dept': is_project_dept
    })


@bp.route('/api/assessment/team-score', methods=['GET'])
def team_assessment_scores():
    """团队综合考核分（管理员）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    if not has_management_right(user['phone']):
        return jsonify({'error': '无权限'}), 403

    period = request.args.get('period', get_period_from_date())

    conn = get_db()
    cur = conn.cursor()

    # 查所有在岗人员
    cur.execute("""
        SELECT id, name, dept, project, position
        FROM personnel
        WHERE (leave_date IS NULL OR leave_date='')
          AND position NOT LIKE '%%司机%%'
          AND position NOT LIKE '%%实习%%'
          AND position NOT LIKE '%%见习%%'
        ORDER BY project, dept, name
    """)
    personnel = cur.fetchall()

    result = []
    for p in personnel:
        # KPI
        cur.execute("""
            SELECT
                COALESCE(SUM(weight), 0) AS tw,
                COALESCE(SUM(CASE
                    WHEN status='已完成' OR COALESCE(progress,0)>=100 THEN weight*100
                    ELSE weight*COALESCE(progress,0)
                END), 0) AS earned
            FROM tasks
            WHERE assignee=%s
              AND (kpi_period=%s OR (kpi_period='' AND TO_CHAR(created_at, 'YYYY-MM')=%s))
        """, (p['name'], period, period))
        kpi_row = cur.fetchone()
        kpi = round(float(kpi_row['earned']) / float(kpi_row['tw']) * 100, 2) if float(kpi_row['tw']) > 0 else 0

        # 产值分
        output = 0
        proj = p.get('project') or ''
        is_proj_dept = proj and proj != '后台' and proj != '未分配'
        if is_proj_dept:
            cur.execute("""
                SELECT
                    COALESCE(SUM(pl.planned_output), 0) AS planned,
                    COALESCE(SUM(CASE WHEN a.review_status='approved' THEN a.output_value ELSE 0 END), 0) AS actual
                FROM projects pr
                LEFT JOIN project_output_plans pl ON pl.project_id=pr.id AND pl.year_month=%s
                LEFT JOIN acceptance_docs a ON a.project_id=pr.id
                    AND TO_CHAR(a.uploaded_at, 'YYYY-MM')=%s
                WHERE pr.dept=%s AND pr.status='active'
            """, (period, period, proj))
            out_row = cur.fetchone()
            planned = float(out_row['planned'] or 0)
            actual = float(out_row['actual'] or 0)
            output = round(actual / planned * 100, 2) if planned > 0 else 0

        # 评价分
        cur.execute("SELECT AVG(total_score) AS avg_score FROM evaluation_scores WHERE evaluatee_id=%s", (p['id'],))
        eval_row = cur.fetchone()
        evl = round(float(eval_row['avg_score'] or 0), 2)

        # 综合分
        # 后台员工：任务KPI 60% + 360评价 40%
        # 项目部员工：产值 60% + 360评价 40%（产值本身就是项目部KPI）
        if is_proj_dept:
            final = round(output * 0.6 + evl * 0.4, 2)
        else:
            final = round(kpi * 0.6 + evl * 0.4, 2)

        result.append({
            'id': p['id'],
            'name': p['name'],
            'dept': p.get('dept') or '',
            'project': proj,
            'position': p.get('position') or '',
            'is_project_dept': is_proj_dept,
            'kpi_score': kpi,
            'output_score': output,
            'eval_score': evl,
            'final_score': final
        })

    # 按综合分降序
    result.sort(key=lambda x: x['final_score'], reverse=True)

    cur.close(); conn.close()
    return jsonify({'period': period, 'scores': result})
