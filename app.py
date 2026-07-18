#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安装公司人员信息管理系统 - Supabase版"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import hashlib
from supabase_config import get_db, init_db

app = Flask(__name__)
CORS(app)

# 初始化数据库
init_db()

# ============= 人员相关API =============

@app.route('/api/personnel')
def get_personnel():
    """获取人员列表"""
    conn = get_db()
    cur = conn.cursor()
    
    category = request.args.get('category', 'all')
    search = request.args.get('search', '').strip()
    
    if category == 'formal':
        cur.execute("SELECT * FROM personnel WHERE category='正式职工' ORDER BY id")
    elif category == 'outsourced':
        cur.execute("SELECT * FROM personnel WHERE category IN ('C1','C2') ORDER BY id")
    elif category == 'C1':
        cur.execute("SELECT * FROM personnel WHERE category='C1' ORDER BY id")
    elif category == 'C2':
        cur.execute("SELECT * FROM personnel WHERE category='C2' ORDER BY id")
    else:
        cur.execute("SELECT * FROM personnel ORDER BY id")
    
    people = cur.fetchall()
    
    if search:
        key = search.lower()
        people = [p for p in people if key in (p['name'] or '').lower() 
                  or key in (p['position'] or '').lower()
                  or key in (p['project'] or '').lower()]
    
    # 排序规则：正式职工→C1→C2；后台在前项目在后；领导在前员在后
    # 特定人员固定顺序
    fixed_order = {'邱方恒': 0, '廖志成': 1, '吕亮': 2, '李强': 3}
    
    def sort_key(p):
        name = p['name'] or ''
        category = p['category'] or ''
        project = p['project'] or '未分配'
        position = p['position'] or ''
        
        # 1. 固定人员优先
        if name in fixed_order:
            return (0, 0, fixed_order[name], 0, 0, name)
        
        # 2. 人员类别：正式职工 > C1 > C2
        if category == '正式职工':
            cat_order = 0
        elif category == 'C1':
            cat_order = 1
        else:
            cat_order = 2
        
        # 3. 项目优先级：后台在前，项目在后
        if project == '后台':
            proj_order = 0
        elif project == '其他':
            proj_order = 999
        else:
            proj_order = 1
        
        # 4. 职务级别：领导在前，员在后
        if any(k in position for k in ['经理', '书记']):
            if '副经理' in position or '生产副经理' in position:
                pos_order = 1
            else:
                pos_order = 0
        elif any(k in position for k in ['部长', '高级主管']):
            pos_order = 2
        elif '主管' in position:
            pos_order = 3
        else:
            pos_order = 4
        
        return (1, cat_order, proj_order, pos_order, 0, name)
    
    people.sort(key=sort_key)
    
    # 转换为JSON格式
    result = []
    for p in people:
        result.append({
            'id': p['id'],
            'name': p['name'],
            'gender': p['gender'] or '',
            'id_card': p['id_card'] or '',
            'birth': p['birth'] or '',
            'edu': p['edu'] or '',
            'hometown': p['hometown'] or '',
            'position': p['position'] or '',
            'project': p['project'] or '未分配',
            'phone': p['phone'] or '',
            'cert': p['cert'] or '',
            'category': p['category'],
            'salary': float(p['salary']) if p['salary'] else None,
            'status': p['status'] or '在岗',
            'status_detail': p['status_detail'] or ''
        })
    
    cur.close()
    conn.close()
    return jsonify(result)

@app.route('/api/personnel/<person_id>')
def get_person(person_id):
    """获取单个人员详情"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM personnel WHERE id=%s", (person_id,))
    p = cur.fetchone()
    cur.close()
    conn.close()
    
    if not p:
        return jsonify({'error': '未找到该人员'}), 404
    
    return jsonify({
        'id': p['id'], 'name': p['name'], 'gender': p['gender'] or '',
        'id_card': p['id_card'] or '', 'birth': p['birth'] or '',
        'edu': p['edu'] or '', 'hometown': p['hometown'] or '',
        'position': p['position'] or '', 'project': p['project'] or '未分配',
        'phone': p['phone'] or '', 'cert': p['cert'] or '',
        'category': p['category'],
        'salary': float(p['salary']) if p['salary'] else None,
        'status': p['status'] or '在岗', 'status_detail': p['status_detail'] or ''
    })

@app.route('/api/personnel', methods=['POST'])
def add_person():
    """新增人员"""
    data = request.json
    if not data.get('name'):
        return jsonify({'error': '姓名不能为空'}), 400
    
    conn = get_db()
    cur = conn.cursor()
    
    # 生成ID
    cat = data.get('category', '正式职工')
    if cat == '正式职工':
        cur.execute("SELECT COUNT(*) FROM personnel WHERE category='正式职工'")
        pid = f"F{cur.fetchone()['count'] + 1}"
    else:
        cur.execute("SELECT COUNT(*) FROM personnel WHERE category IN ('C1','C2')")
        pid = f"O{cur.fetchone()['count'] + 1}"
    
    cur.execute("""
        INSERT INTO personnel (id, name, gender, id_card, birth, edu, hometown, position, project, phone, cert, category, salary)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (pid, data['name'], data.get('gender',''), data.get('id_card',''),
          data.get('birth',''), data.get('edu',''), data.get('hometown',''),
          data.get('position',''), data.get('project','未分配'),
          data.get('phone',''), data.get('cert',''), cat, data.get('salary')))
    
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'person': {'id': pid, **data}})

@app.route('/api/personnel/<person_id>', methods=['PUT'])
def update_person(person_id):
    """更新人员信息"""
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT id FROM personnel WHERE id=%s", (person_id,))
    if not cur.fetchone():
        cur.close(); conn.close()
        return jsonify({'error': '未找到该人员'}), 404
    
    fields = []
    values = []
    for key in ['name','gender','id_card','birth','edu','hometown','position','project','phone','cert','salary','status','status_detail']:
        if key in data:
            fields.append(f"{key}=%s")
            values.append(data[key])
    
    if fields:
        fields.append("updated_at=NOW()")
        values.append(person_id)
        cur.execute(f"UPDATE personnel SET {','.join(fields)} WHERE id=%s", values)
        conn.commit()
    
    cur.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/personnel/<person_id>', methods=['DELETE'])
def delete_person(person_id):
    """删除人员"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM personnel WHERE id=%s", (person_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

# ============= 状态管理API =============

@app.route('/api/personnel/<person_id>/status', methods=['PUT'])
def update_status(person_id):
    """更新人员状态"""
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE personnel SET status=%s, status_detail=%s, updated_at=NOW() WHERE id=%s",
                (data.get('status','在岗'), data.get('detail',''), person_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/personnel/<person_id>/return', methods=['PUT'])
def person_return(person_id):
    """归队/销假"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE personnel SET status='在岗', status_detail='', updated_at=NOW() WHERE id=%s", (person_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

# ============= 调动记录API =============

@app.route('/api/transfers')
def get_transfers():
    """获取调动记录"""
    conn = get_db()
    cur = conn.cursor()
    person_id = request.args.get('person_id')
    
    if person_id:
        cur.execute("SELECT * FROM transfers WHERE person_id=%s ORDER BY created_at DESC", (person_id,))
    else:
        cur.execute("SELECT * FROM transfers ORDER BY created_at DESC")
    
    records = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in records])

@app.route('/api/transfers', methods=['POST'])
def add_transfer():
    """新增调动记录"""
    data = request.json
    if not data.get('person_id') or not data.get('to_project'):
        return jsonify({'error': '信息不完整'}), 400
    
    conn = get_db()
    cur = conn.cursor()
    
    # 获取原项目
    cur.execute("SELECT project FROM personnel WHERE id=%s", (data['person_id'],))
    person = cur.fetchone()
    from_project = person['project'] if person else ''
    
    # 生成ID
    cur.execute("SELECT COUNT(*) FROM transfers")
    tid = f"T{cur.fetchone()['count'] + 1}"
    
    cur.execute("""
        INSERT INTO transfers (id, person_id, person_name, from_project, to_project, transfer_date, notes, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (tid, data['person_id'], data.get('person_name',''), from_project,
          data['to_project'], data.get('transfer_date',''), data.get('notes',''),
          datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    # 更新人员项目
    cur.execute("UPDATE personnel SET project=%s, updated_at=NOW() WHERE id=%s",
                (data['to_project'], data['person_id']))
    
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'transfer': {'id': tid, **data}})

@app.route('/api/personnel/<person_id>/timeline')
def get_timeline(person_id):
    """获取项目时间线"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM transfers WHERE person_id=%s ORDER BY transfer_date", (person_id,))
    transfers = cur.fetchall()
    
    cur.execute("SELECT project FROM personnel WHERE id=%s", (person_id,))
    person = cur.fetchone()
    current_project = person['project'] if person else '未分配'
    
    timeline = []
    if not transfers:
        timeline.append({'project': current_project, 'start_date': '至今', 'end_date': '至今', 'months': 12})
    
    cur.close()
    conn.close()
    return jsonify({
        'person_id': person_id,
        'current_project': current_project,
        'timeline': timeline,
        'transfers': [dict(t) for t in transfers]
    })

# ============= 休假申请API =============

@app.route('/api/leave')
def get_leave():
    """获取休假申请"""
    conn = get_db()
    cur = conn.cursor()
    person_id = request.args.get('person_id')
    
    if person_id:
        cur.execute("SELECT * FROM leave_records WHERE person_id=%s ORDER BY created_at DESC", (person_id,))
    else:
        cur.execute("SELECT * FROM leave_records ORDER BY created_at DESC")
    
    records = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in records])

@app.route('/api/leave', methods=['POST'])
def add_leave():
    """新增休假申请"""
    data = request.json
    if not data.get('person_id') or not data.get('start_date') or not data.get('end_date'):
        return jsonify({'error': '信息不完整'}), 400
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM leave_records")
    lid = f"L{cur.fetchone()['count'] + 1}"
    
    cur.execute("""
        INSERT INTO leave_records (id, person_id, person_name, start_date, end_date, reason, status, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (lid, data['person_id'], data.get('person_name',''),
          data['start_date'], data['end_date'], data.get('reason',''),
          '待审批', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'record': {'id': lid, **data}})

@app.route('/api/leave/<record_id>/approve', methods=['PUT'])
def approve_leave(record_id):
    """审批休假"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("UPDATE leave_records SET status='已通过' WHERE id=%s RETURNING person_id, end_date", (record_id,))
    record = cur.fetchone()
    
    if record:
        cur.execute("UPDATE personnel SET status='休假', status_detail=%s, updated_at=NOW() WHERE id=%s",
                    (f"休假至{record['end_date']}", record['person_id']))
        conn.commit()
    
    cur.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/leave/<record_id>/reject', methods=['PUT'])
def reject_leave(record_id):
    """驳回休假"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE leave_records SET status='已驳回' WHERE id=%s", (record_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

# ============= 出差单API =============

@app.route('/api/trip')
def get_trips():
    """获取出差单"""
    conn = get_db()
    cur = conn.cursor()
    person_id = request.args.get('person_id')
    
    if person_id:
        cur.execute("SELECT * FROM trip_records WHERE person_id=%s ORDER BY created_at DESC", (person_id,))
    else:
        cur.execute("SELECT * FROM trip_records ORDER BY created_at DESC")
    
    records = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in records])

@app.route('/api/trip', methods=['POST'])
def add_trip():
    """新增出差单"""
    data = request.json
    if not data.get('person_id') or not data.get('destination'):
        return jsonify({'error': '信息不完整'}), 400
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM trip_records")
    bid = f"B{cur.fetchone()['count'] + 1}"
    
    cur.execute("""
        INSERT INTO trip_records (id, person_id, person_name, destination, start_date, end_date, reason, status, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (bid, data['person_id'], data.get('person_name',''),
          data['destination'], data.get('start_date',''), data.get('end_date',''),
          data.get('reason',''), '待审批', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'record': {'id': bid, **data}})

@app.route('/api/trip/<record_id>/approve', methods=['PUT'])
def approve_trip(record_id):
    """审批出差"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("UPDATE trip_records SET status='已通过' WHERE id=%s RETURNING person_id, destination", (record_id,))
    record = cur.fetchone()
    
    if record:
        cur.execute("UPDATE personnel SET status='出差', status_detail=%s, updated_at=NOW() WHERE id=%s",
                    (f"出差-{record['destination']}", record['person_id']))
        conn.commit()
    
    cur.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/trip/<record_id>/reject', methods=['PUT'])
def reject_trip(record_id):
    """驳回出差"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE trip_records SET status='已驳回' WHERE id=%s", (record_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

# ============= 统计API =============

@app.route('/api/statistics')
def get_statistics():
    """获取统计数据"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) as total FROM personnel")
    total = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as c FROM personnel WHERE category='正式职工'")
    formal = cur.fetchone()['c']
    
    cur.execute("SELECT COUNT(*) as c FROM personnel WHERE category='C1'")
    c1 = cur.fetchone()['c']
    
    cur.execute("SELECT COUNT(*) as c FROM personnel WHERE category='C2'")
    c2 = cur.fetchone()['c']
    
    cur.execute("SELECT COUNT(*) as c FROM personnel WHERE gender='男'")
    male = cur.fetchone()['c']
    
    cur.execute("SELECT COUNT(*) as c FROM personnel WHERE gender='女'")
    female = cur.fetchone()['c']
    
    # 学历统计
    def map_edu(edu):
        if not edu: return '未知'
        if any(k in edu for k in ['本科','大学']): return '本科'
        if any(k in edu for k in ['专科','大专']): return '专科'
        if any(k in edu for k in ['中专','初中','高中']): return '高中及以下'
        return '未知'
    
    cur.execute("SELECT edu FROM personnel")
    edu_stats = {}
    for row in cur.fetchall():
        cat = map_edu(row['edu'])
        edu_stats[cat] = edu_stats.get(cat, 0) + 1
    
    # 项目统计
    cur.execute("SELECT project, COUNT(*) as c FROM personnel WHERE category='正式职工' GROUP BY project")
    dept_stats = {row['project']: row['c'] for row in cur.fetchall()}
    
    cur.close()
    conn.close()
    
    return jsonify({
        'total': total,
        'formal_count': formal,
        'outsourced_count': c1 + c2,
        'c1_count': c1,
        'c2_count': c2,
        'gender': {'male': male, 'female': female},
        'edu': edu_stats,
        'dept': dept_stats
    })

# ============= 登录API =============

@app.route('/api/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.json
    phone = data.get('phone','').strip()
    password = data.get('password','').strip()
    
    if not phone or not password:
        return jsonify({'error': '手机号和密码不能为空'}), 400
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE phone=%s", (phone,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if not user:
        return jsonify({'error': '用户不存在'}), 401
    if user['password'] != password:
        return jsonify({'error': '密码错误'}), 401
    
    token = hashlib.md5(f"{phone}:{password}:{datetime.now().date()}".encode()).hexdigest()
    
    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'phone': user['phone'],
            'name': user['name'],
            'is_admin': user['is_admin']
        }
    })

# ============= Render部署 =============
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
