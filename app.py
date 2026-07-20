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

def get_dept(person):
    """根据职位和项目自动推断部门"""
    position = (person.get('position', '') or '').lower()
    project = person.get('project', '') or ''
    
    # 领导班子
    if any(k in position for k in ['经理', '书记']):
        return '领导班子'
    
    # 后台人员
    if project == '后台':
        if any(k in position for k in ['bim', '设计']):
            return '质量技术部'
        elif any(k in position for k in ['商务', '预算', '造价', '结算']):
            return '商务法务部'
        elif any(k in position for k in ['财务', '会计']):
            return '财务部'
        elif any(k in position for k in ['安全']):
            return '安全环保部'
        else:
            return '综合办公室'
    
    # 项目人员
    if any(k in position for k in ['商务', '预算', '造价', '结算']):
        return '商务法务部'
    elif any(k in position for k in ['安全']):
        return '安全环保部'
    else:
        return '工程技术部'

@app.route('/api/personnel')
def get_personnel():
    """获取人员列表"""
    conn = get_db()
    cur = conn.cursor()
    
    category = request.args.get('category', 'all')
    search = request.args.get('search', '').strip()
    
    if category == 'formal':
        cur.execute("SELECT * FROM personnel WHERE category='正式职工'")
    elif category == 'outsourced':
        cur.execute("SELECT * FROM personnel WHERE category IN ('C1','C2')")
    elif category == 'C1':
        cur.execute("SELECT * FROM personnel WHERE category='C1'")
    elif category == 'C2':
        cur.execute("SELECT * FROM personnel WHERE category='C2'")
    else:
        cur.execute("SELECT * FROM personnel")
    
    people = cur.fetchall()
    
    if search:
        key = search.lower()
        people = [p for p in people if key in (p['name'] or '').lower() 
                  or key in (p['position'] or '').lower()
                  or key in (p['project'] or '').lower()]
    
    # 排序逻辑
    def sort_key(p):
        # 1. 固定人员优先
        fixed_order = {'邱方恒': 0, '廖志成': 1, '吕亮': 2, '李强': 3}
        fixed = fixed_order.get(p['name'], 99)
        
        # 2. 人员类别
        cat_order = {'正式职工': 0, 'C1': 1, 'C2': 2}
        cat = cat_order.get(p.get('category', ''), 3)
        
        # 3. 项目优先级
        project = p.get('project', '') or ''
        if project == '后台':
            proj = 0
        elif project and project != '其他':
            proj = 1
        else:
            proj = 2
        
        # 4. 职务级别
        position = (p.get('position', '') or '').lower()
        if any(k in position for k in ['经理', '书记']):
            pos = 0
        elif any(k in position for k in ['部长', '主管', '副部长']):
            pos = 1
        else:
            pos = 2
        
        return (fixed, cat, proj, pos, p.get('name', ''))
    
    people.sort(key=sort_key)
    
    # 转换为JSON格式
    result = []
    for p in people:
        # 如果dept为空，自动推断
        dept = p.get('dept', '') or ''
        if not dept:
            dept = get_dept(p)
        
        result.append({
            'id': p['id'],
            'name': p['name'],
            'gender': p['gender'] or '',
            'id_card': p['id_card'] or '',
            'birth': p['birth'] or '',
            'edu': p['edu'] or '',
            'hometown': p['hometown'] or '',
            'position': p['position'] or '',
            'dept': dept,
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
    
    # 如果dept为空，自动推断
    dept = p.get('dept', '') or ''
    if not dept:
        dept = get_dept(p)
    
    return jsonify({
        'id': p['id'], 'name': p['name'], 'gender': p['gender'] or '',
        'id_card': p['id_card'] or '', 'birth': p['birth'] or '',
        'edu': p['edu'] or '', 'hometown': p['hometown'] or '',
        'position': p['position'] or '', 'dept': dept,
        'project': p['project'] or '未分配',
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
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # 生成ID（找最大编号+1，避免重复）
        cat = data.get('category', '正式职工')
        if cat == '正式职工':
            cur.execute("SELECT id FROM personnel WHERE id LIKE 'F%' ORDER BY CAST(SUBSTRING(id FROM 2) AS INTEGER) DESC LIMIT 1")
        else:
            cur.execute("SELECT id FROM personnel WHERE id LIKE 'O%' ORDER BY CAST(SUBSTRING(id FROM 2) AS INTEGER) DESC LIMIT 1")
        
        row = cur.fetchone()
        if row and row['id']:
            max_num = int(row['id'][1:])
            pid = f"{'F' if cat == '正式职工' else 'O'}{max_num + 1}"
        else:
            pid = f"{'F' if cat == '正式职工' else 'O'}1"
        
        # salary转数字，空字符串转None
        salary = data.get('salary')
        if salary == '' or salary is None:
            salary = None
        else:
            try:
                salary = float(salary)
            except:
                salary = None
        
        cur.execute("""
            INSERT INTO personnel (id, name, gender, id_card, birth, edu, hometown, position, dept, project, phone, cert, category, salary)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (pid, data['name'], data.get('gender',''), data.get('id_card',''),
              data.get('birth',''), data.get('edu',''), data.get('hometown',''),
              data.get('position',''), data.get('dept',''),
              data.get('project','未分配'),
              data.get('phone',''), data.get('cert',''), cat, salary))
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'person': {'id': pid, **data}})
    except Exception as e:
        print(f"add_person error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/personnel/<person_id>', methods=['PUT'])
def update_person(person_id):
    """更新人员信息"""
    data = request.json
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT id FROM personnel WHERE id=%s", (person_id,))
        if not cur.fetchone():
            cur.close(); conn.close()
            return jsonify({'error': '未找到该人员'}), 404
        
        fields = []
        values = []
        for key in ['name','gender','id_card','birth','edu','hometown','position','dept','project','phone','cert','category','salary','status','status_detail']:
            if key in data:
                val = data[key]
                # salary空字符串转None
                if key == 'salary' and (val == '' or val is None):
                    val = None
                fields.append(f"{key}=%s")
                values.append(val)
        
        if fields:
            fields.append("updated_at=NOW()")
            values.append(person_id)
            cur.execute(f"UPDATE personnel SET {','.join(fields)} WHERE id=%s", values)
            conn.commit()
        
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        print(f"update_person error: {e}")
        return jsonify({'error': str(e)}), 500

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
    
    # 证书统计
    cur.execute("SELECT name, cert FROM personnel")
    cert_stats = {
        '一建': {'count': 0, 'persons': []},
        '一造': {'count': 0, 'persons': []},
        '二建': {'count': 0, 'persons': []},
        '二造': {'count': 0, 'persons': []},
        '八大员': {'count': 0, 'detail': {}},
        '其他': {'count': 0, 'persons': []},
        '无证书': {'count': 0, 'persons': []}
    }
    total_with_cert = 0
    
    # 八大员证书关键词分类
    badayuan_types = ['质量员', '施工员', '安全员', '测量员', '资料员', '材料员', '机械员', '劳务员', '标准员', '试验员']
    
    for row in cur.fetchall():
        name = row['name']
        cert = row['cert']
        if cert and cert.strip() and cert != '/':
            total_with_cert += 1
            if '一建' in cert or '一级建造师' in cert:
                cert_stats['一建']['count'] += 1
                cert_stats['一建']['persons'].append(name)
            elif '一造' in cert or '一级造价' in cert:
                cert_stats['一造']['count'] += 1
                cert_stats['一造']['persons'].append(name)
            elif '二建' in cert or '二级建造师' in cert:
                cert_stats['二建']['count'] += 1
                cert_stats['二建']['persons'].append(name)
            elif '二造' in cert or '二级造价' in cert:
                cert_stats['二造']['count'] += 1
                cert_stats['二造']['persons'].append(name)
            elif any(k in cert for k in badayuan_types):
                cert_stats['八大员']['count'] += 1
                # 按证书子类型分组
                found_type = '其他'
                for t in badayuan_types:
                    if t in cert:
                        found_type = t
                        break
                if found_type not in cert_stats['八大员']['detail']:
                    cert_stats['八大员']['detail'][found_type] = []
                cert_stats['八大员']['detail'][found_type].append(name)
            else:
                cert_stats['其他']['count'] += 1
                cert_stats['其他']['persons'].append(f"{name}（{cert}）")
        else:
            cert_stats['无证书']['count'] += 1
            cert_stats['无证书']['persons'].append(name)
    
    # 一建指标
    cur.execute("SELECT * FROM exam_targets WHERE exam_type='一建' LIMIT 1")
    exam_row = cur.fetchone()
    exam_target = None
    if exam_row:
        cur.execute("SELECT person_name FROM exam_target_persons WHERE target_id=%s ORDER BY id", (exam_row['id'],))
        persons = [r['person_name'] for r in cur.fetchall()]
        exam_target = {
            'id': exam_row['id'],
            'exam_type': exam_row['exam_type'],
            'year': exam_row['year'],
            'persons': persons
        }
    
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
        'dept': dept_stats,
        'cert': cert_stats,
        'exam_target': exam_target
    })

# ============= 登录API =============

# ============= 一建指标API =============

@app.route('/api/exam-targets', methods=['GET'])
def get_exam_targets():
    """获取一建指标"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM exam_targets ORDER BY year DESC LIMIT 1")
    target = cur.fetchone()
    
    if target:
        cur.execute("SELECT person_name FROM exam_target_persons WHERE target_id=%s ORDER BY id", (target['id'],))
        persons = [r['person_name'] for r in cur.fetchall()]
        result = {
            'id': target['id'],
            'exam_type': target['exam_type'],
            'year': target['year'],
            'persons': persons
        }
    else:
        result = None
    
    cur.close()
    conn.close()
    return jsonify(result)

@app.route('/api/exam-targets', methods=['POST'])
def save_exam_targets():
    """保存一建指标"""
    data = request.json
    exam_type = data.get('exam_type', '一建')
    year = data.get('year', 2026)
    persons = data.get('persons', [])
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 查找或创建指标
        cur.execute("SELECT id FROM exam_targets WHERE exam_type=%s AND year=%s", (exam_type, year))
        row = cur.fetchone()
        
        if row:
            target_id = row['id']
            # 更新时间
            cur.execute("UPDATE exam_targets SET updated_at=NOW() WHERE id=%s", (target_id,))
            # 删除旧人员
            cur.execute("DELETE FROM exam_target_persons WHERE target_id=%s", (target_id,))
        else:
            cur.execute("INSERT INTO exam_targets (exam_type, year) VALUES (%s, %s) RETURNING id", (exam_type, year))
            target_id = cur.fetchone()['id']
        
        # 插入新人员
        for name in persons:
            cur.execute("INSERT INTO exam_target_persons (target_id, person_name) VALUES (%s, %s)", (target_id, name))
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({'error': str(e)}), 500

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
