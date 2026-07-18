#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安装公司人员信息管理系统 - 支持跨域访问
"""

from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side
import json
import os
import io
from datetime import datetime, date
from copy import copy

app = Flask(__name__)

# 启用跨域支持（小程序必须）
CORS(app)

# 数据文件路径
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
ROSTER_FILE = os.path.join(DATA_DIR, '安装公司最新人员花名册.xlsx')
TRANSFER_FILE = os.path.join(DATA_DIR, '人员调动记录.xlsx')
STATUS_FILE = os.path.join(DATA_DIR, '人员状态.json')
LEAVE_FILE = os.path.join(DATA_DIR, '休假申请表.xlsx')
TRIP_FILE = os.path.join(DATA_DIR, '出差单.xlsx')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

def ensure_data_dir():
    """确保数据目录存在"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

# ============= 用户管理 =============

def load_users():
    """加载用户数据"""
    if not os.path.exists(USERS_FILE):
        # 默认管理员账号
        default_users = {
            '18184005669': {
                'phone': '18184005669',
                'name': '管理员',
                'password': '123456',
                'is_admin': True
            }
        }
        save_users(default_users)
        return default_users
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users(users_data):
    """保存用户数据"""
    ensure_data_dir()
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

# ============= 状态管理 =============

def load_status():
    """加载人员状态"""
    if not os.path.exists(STATUS_FILE):
        return {}
    with open(STATUS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_status(status_data):
    """保存人员状态"""
    ensure_data_dir()
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status_data, f, ensure_ascii=False, indent=2)

def get_person_status(person_id):
    """获取人员当前状态"""
    status = load_status()
    return status.get(person_id, {'status': '在岗', 'detail': ''})

# ============= 休假/出差记录 =============

def load_leave_records():
    """加载休假申请"""
    if not os.path.exists(LEAVE_FILE):
        return []
    wb = openpyxl.load_workbook(LEAVE_FILE, data_only=True)
    ws = wb.active
    records = []
    for r in range(2, ws.max_row + 1):
        rid = ws.cell(r, 1).value
        if rid:
            records.append({
                'id': rid,
                'person_id': ws.cell(r, 2).value or '',
                'person_name': ws.cell(r, 3).value or '',
                'start_date': str(ws.cell(r, 4).value or ''),
                'end_date': str(ws.cell(r, 5).value or ''),
                'reason': ws.cell(r, 6).value or '',
                'status': ws.cell(r, 7).value or '待审批',
                'created_at': str(ws.cell(r, 8).value or '')
            })
    return records

def save_leave_records(records):
    """保存休假申请"""
    ensure_data_dir()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '休假申请'
    headers = ['编号', '人员ID', '姓名', '开始日期', '结束日期', '事由', '审批状态', '申请时间']
    for i, h in enumerate(headers, 1):
        ws.cell(1, i, h)
        ws.cell(1, i).font = Font(name='宋体', size=10, bold=True)
        ws.cell(1, i).alignment = Alignment(horizontal='center', vertical='center')
    for idx, r in enumerate(records, 2):
        ws.cell(idx, 1, r['id'])
        ws.cell(idx, 2, r['person_id'])
        ws.cell(idx, 3, r['person_name'])
        ws.cell(idx, 4, r['start_date'])
        ws.cell(idx, 5, r['end_date'])
        ws.cell(idx, 6, r['reason'])
        ws.cell(idx, 7, r['status'])
        ws.cell(idx, 8, r['created_at'])
    for col in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
        ws.column_dimensions[col].width = 15
    ws.column_dimensions['F'].width = 30
    wb.save(LEAVE_FILE)

def load_trip_records():
    """加载出差单"""
    if not os.path.exists(TRIP_FILE):
        return []
    wb = openpyxl.load_workbook(TRIP_FILE, data_only=True)
    ws = wb.active
    records = []
    for r in range(2, ws.max_row + 1):
        rid = ws.cell(r, 1).value
        if rid:
            records.append({
                'id': rid,
                'person_id': ws.cell(r, 2).value or '',
                'person_name': ws.cell(r, 3).value or '',
                'destination': ws.cell(r, 4).value or '',
                'start_date': str(ws.cell(r, 5).value or ''),
                'end_date': str(ws.cell(r, 6).value or ''),
                'reason': ws.cell(r, 7).value or '',
                'status': ws.cell(r, 8).value or '待审批',
                'created_at': str(ws.cell(r, 9).value or '')
            })
    return records

def save_trip_records(records):
    """保存出差单"""
    ensure_data_dir()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '出差单'
    headers = ['编号', '人员ID', '姓名', '出差目的地', '开始日期', '结束日期', '事由', '审批状态', '申请时间']
    for i, h in enumerate(headers, 1):
        ws.cell(1, i, h)
        ws.cell(1, i).font = Font(name='宋体', size=10, bold=True)
        ws.cell(1, i).alignment = Alignment(horizontal='center', vertical='center')
    for idx, r in enumerate(records, 2):
        ws.cell(idx, 1, r['id'])
        ws.cell(idx, 2, r['person_id'])
        ws.cell(idx, 3, r['person_name'])
        ws.cell(idx, 4, r['destination'])
        ws.cell(idx, 5, r['start_date'])
        ws.cell(idx, 6, r['end_date'])
        ws.cell(idx, 7, r['reason'])
        ws.cell(idx, 8, r['status'])
        ws.cell(idx, 9, r['created_at'])
    for col in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']:
        ws.column_dimensions[col].width = 15
    ws.column_dimensions['G'].width = 30
    wb.save(TRIP_FILE)

def load_personnel_data():
    """从Excel加载人员数据"""
    if not os.path.exists(ROSTER_FILE):
        return {'formal': [], 'outsourced': []}
    
    wb = openpyxl.load_workbook(ROSTER_FILE, data_only=True)
    
    result = {'formal': [], 'outsourced': []}
    
    # 读取正式职工
    if '正式职工' in wb.sheetnames:
        ws = wb['正式职工']
        for r in range(3, ws.max_row + 1):
            name = ws.cell(r, 2).value
            if name:
                person = {
                    'id': f'F{r-2}',
                    'seq': ws.cell(r, 1).value,
                    'name': name,
                    'gender': ws.cell(r, 3).value or '',
                    'id_card': str(ws.cell(r, 4).value or ''),
                    'birth': str(ws.cell(r, 5).value or ''),
                    'edu': ws.cell(r, 6).value or '',
                    'hometown': ws.cell(r, 7).value or '',
                    'position': ws.cell(r, 8).value or '',
                    'project': ws.cell(r, 9).value or '未分配',
                    'phone': str(ws.cell(r, 10).value or ''),
                    'cert': ws.cell(r, 11).value or '',
                    'category': '正式职工',
                    'status': ws.cell(r, 12).value or '在岗',
                    'status_detail': ws.cell(r, 13).value or ''
                }
                result['formal'].append(person)
    
    # 读取劳务外包人员
    if '劳务外包人员' in wb.sheetnames:
        ws = wb['劳务外包人员']
        current_category = ''
        for r in range(3, ws.max_row + 1):
            val1 = ws.cell(r, 1).value
            if val1 and 'C1类' in str(val1):
                current_category = 'C1'
                continue
            elif val1 and 'C2类' in str(val1):
                current_category = 'C2'
                continue
            
            name = ws.cell(r, 2).value
            if name and current_category:
                project = ws.cell(r, 12).value or '未分配'
                cert = ws.cell(r, 13).value or ''
                
                person = {
                    'id': f'O{r-2}',
                    'seq': ws.cell(r, 1).value,
                    'name': name,
                    'gender': ws.cell(r, 3).value or '',
                    'id_card': str(ws.cell(r, 4).value or ''),
                    'birth': str(ws.cell(r, 5).value or ''),
                    'edu': ws.cell(r, 6).value or '',
                    'hometown': ws.cell(r, 7).value or '',
                    'position': ws.cell(r, 8).value or '',
                    'salary': ws.cell(r, 9).value or '',
                    'category': current_category,
                    'phone': str(ws.cell(r, 11).value or ''),
                    'project': project,
                    'cert': cert,
                    'status': ws.cell(r, 14).value or '在岗',
                    'status_detail': ws.cell(r, 15).value or ''
                }
                result['outsourced'].append(person)
    
    return result

def save_personnel_data(data):
    """保存人员数据到Excel"""
    ensure_data_dir()
    wb = openpyxl.load_workbook(ROSTER_FILE)
    
    # 保存正式职工
    if '正式职工' in wb.sheetnames:
        ws = wb['正式职工']
        for i, p in enumerate(data['formal']):
            row = i + 3
            ws.cell(row, 1, p.get('seq', i + 1))
            ws.cell(row, 2, p.get('name', ''))
            ws.cell(row, 3, p.get('gender', ''))
            ws.cell(row, 4, p.get('id_card', ''))
            ws.cell(row, 5, p.get('birth', ''))
            ws.cell(row, 6, p.get('edu', ''))
            ws.cell(row, 7, p.get('hometown', ''))
            ws.cell(row, 8, p.get('position', ''))
            ws.cell(row, 9, p.get('project', ''))
            ws.cell(row, 10, p.get('phone', ''))
            ws.cell(row, 11, p.get('cert', ''))
    
    wb.save(ROSTER_FILE)

def load_transfer_data():
    """加载调动记录"""
    if not os.path.exists(TRANSFER_FILE):
        return []
    
    wb = openpyxl.load_workbook(TRANSFER_FILE, data_only=True)
    ws = wb.active
    
    transfers = []
    for r in range(2, ws.max_row + 1):
        transfer_id = ws.cell(r, 1).value
        if transfer_id:
            transfer = {
                'id': transfer_id,
                'person_id': ws.cell(r, 2).value or '',
                'person_name': ws.cell(r, 3).value or '',
                'from_project': ws.cell(r, 4).value or '',
                'to_project': ws.cell(r, 5).value or '',
                'transfer_date': str(ws.cell(r, 6).value or ''),
                'notes': ws.cell(r, 7).value or '',
                'created_at': str(ws.cell(r, 8).value or '')
            }
            transfers.append(transfer)
    
    return transfers

def save_transfer_data(transfers):
    """保存调动记录"""
    ensure_data_dir()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '调动记录'
    
    # 标题
    ws.merge_cells('A1:H1')
    ws.cell(1, 1, '安装公司人员调动记录表')
    ws.cell(1, 1).font = Font(name='黑体', size=14, bold=True)
    ws.cell(1, 1).alignment = Alignment(horizontal='center', vertical='center')
    
    # 表头
    headers = ['调动编号', '人员ID', '姓名', '原项目', '新项目', '调动日期', '备注', '录入时间']
    for i, h in enumerate(headers, 1):
        ws.cell(2, i, h)
        ws.cell(2, i).font = Font(name='宋体', size=10, bold=True)
        ws.cell(2, i).alignment = Alignment(horizontal='center', vertical='center')
    
    # 数据
    for idx, t in enumerate(transfers, 1):
        row = idx + 2
        ws.cell(row, 1, t['id'])
        ws.cell(row, 2, t['person_id'])
        ws.cell(row, 3, t['person_name'])
        ws.cell(row, 4, t['from_project'])
        ws.cell(row, 5, t['to_project'])
        ws.cell(row, 6, t['transfer_date'])
        ws.cell(row, 7, t['notes'])
        ws.cell(row, 8, t['created_at'])
    
    # 设置列宽
    ws.column_dimensions['A'].width = 12
    ws.column_dimensions['B'].width = 10
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 15
    ws.column_dimensions['E'].width = 15
    ws.column_dimensions['F'].width = 15
    ws.column_dimensions['G'].width = 30
    ws.column_dimensions['H'].width = 20
    
    wb.save(TRANSFER_FILE)
    return True

def update_personnel_project(person_id, new_project):
    """更新人员的当前项目"""
    wb = openpyxl.load_workbook(ROSTER_FILE)
    
    # 判断是正式职工还是外包人员
    if person_id.startswith('F'):
        ws = wb['正式职工']
        row_idx = int(person_id[1:]) + 2
        if row_idx <= ws.max_row:
            ws.cell(row_idx, 9, new_project)
    else:
        ws = wb['劳务外包人员']
        # 需要找到对应的人
        current_cat = ''
        count = 0
        for r in range(3, ws.max_row + 1):
            val1 = ws.cell(r, 1).value
            if val1 and 'C1类' in str(val1):
                current_cat = 'C1'
                continue
            elif val1 and 'C2类' in str(val1):
                current_cat = 'C2'
                continue
            
            name = ws.cell(r, 2).value
            if name and current_cat:
                count += 1
                if f'O{count}' == person_id:
                    ws.cell(r, 12, new_project)
                    break
    
    wb.save(ROSTER_FILE)

# ============= 人员相关API =============

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/api/personnel')
def get_personnel():
    """获取人员列表"""
    data = load_personnel_data()
    category = request.args.get('category', 'all')
    search = request.args.get('search', '').strip()
    
    if category == 'formal':
        people = data['formal']
    elif category == 'outsourced':
        people = data['outsourced']
    else:
        people = data['formal'] + data['outsourced']
    
    if search:
        people = [p for p in people if search in p['name'] or search in p.get('position', '') or search in p.get('project', '')]
    
    return jsonify(people)

@app.route('/api/personnel/<person_id>')
def get_person(person_id):
    """获取单个人员详情"""
    data = load_personnel_data()
    all_people = data['formal'] + data['outsourced']
    
    for p in all_people:
        if p['id'] == person_id:
            return jsonify(p)
    
    return jsonify({'error': '未找到该人员'}), 404

@app.route('/api/personnel', methods=['POST'])
def add_person():
    """新增人员"""
    data = load_personnel_data()
    person = request.json
    
    if not person.get('name'):
        return jsonify({'error': '姓名不能为空'}), 400
    
    if person.get('category') == '正式职工':
        person['id'] = f'F{len(data["formal"]) + 1}'
        data['formal'].append(person)
    else:
        person['id'] = f'O{len(data["outsourced"]) + 1}'
        data['outsourced'].append(person)
    
    save_personnel_data(data)
    return jsonify({'success': True, 'person': person})

@app.route('/api/personnel/<person_id>', methods=['PUT'])
def update_person(person_id):
    """更新人员信息"""
    data = load_personnel_data()
    updated = request.json
    
    for i, p in enumerate(data['formal']):
        if p['id'] == person_id:
            data['formal'][i].update(updated)
            save_personnel_data(data)
            return jsonify({'success': True})
    
    for i, p in enumerate(data['outsourced']):
        if p['id'] == person_id:
            data['outsourced'][i].update(updated)
            save_personnel_data(data)
            return jsonify({'success': True})
    
    return jsonify({'error': '未找到该人员'}), 404

@app.route('/api/personnel/<person_id>', methods=['DELETE'])
def delete_person(person_id):
    """删除人员"""
    data = load_personnel_data()
    
    for i, p in enumerate(data['formal']):
        if p['id'] == person_id:
            data['formal'].pop(i)
            save_personnel_data(data)
            return jsonify({'success': True})
    
    for i, p in enumerate(data['outsourced']):
        if p['id'] == person_id:
            data['outsourced'].pop(i)
            save_personnel_data(data)
            return jsonify({'success': True})
    
    return jsonify({'error': '未找到该人员'}), 404

# ============= 调动相关API =============

@app.route('/api/transfers')
def get_transfers():
    """获取调动记录列表"""
    transfers = load_transfer_data()
    person_id = request.args.get('person_id')
    
    if person_id:
        transfers = [t for t in transfers if t['person_id'] == person_id]
    
    # 按调动日期倒序
    transfers.sort(key=lambda x: x.get('transfer_date', ''), reverse=True)
    
    return jsonify(transfers)

@app.route('/api/transfers/<transfer_id>')
def get_transfer(transfer_id):
    """获取单条调动记录"""
    transfers = load_transfer_data()
    
    for t in transfers:
        if t['id'] == transfer_id:
            return jsonify(t)
    
    return jsonify({'error': '未找到调动记录'}), 404

@app.route('/api/transfers', methods=['POST'])
def add_transfer():
    """新增调动记录"""
    data = request.json
    
    if not data.get('person_id') or not data.get('person_name'):
        return jsonify({'error': '人员信息不完整'}), 400
    
    if not data.get('to_project'):
        return jsonify({'error': '请选择调入项目'}), 400
    
    if not data.get('transfer_date'):
        return jsonify({'error': '请选择调动日期'}), 400
    
    # 加载现有记录
    transfers = load_transfer_data()
    
    # 获取人员当前项目作为原项目
    personnel = load_personnel_data()
    all_people = personnel['formal'] + personnel['outsourced']
    from_project = ''
    for p in all_people:
        if p['id'] == data['person_id']:
            from_project = p.get('project', '未分配')
            break
    
    # 创建新调动记录
    new_transfer = {
        'id': f'T{len(transfers) + 1}',
        'person_id': data['person_id'],
        'person_name': data['person_name'],
        'from_project': from_project,
        'to_project': data['to_project'],
        'transfer_date': data['transfer_date'],
        'notes': data.get('notes', ''),
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    transfers.append(new_transfer)
    save_transfer_data(transfers)
    
    # 更新人员的当前项目
    update_personnel_project(data['person_id'], data['to_project'])
    
    return jsonify({'success': True, 'transfer': new_transfer})

@app.route('/api/transfers/<transfer_id>', methods=['PUT'])
def update_transfer(transfer_id):
    """更新调动记录"""
    data = request.json
    transfers = load_transfer_data()
    
    for i, t in enumerate(transfers):
        if t['id'] == transfer_id:
            transfers[i].update(data)
            save_transfer_data(transfers)
            return jsonify({'success': True})
    
    return jsonify({'error': '未找到调动记录'}), 404

@app.route('/api/transfers/<transfer_id>', methods=['DELETE'])
def delete_transfer(transfer_id):
    """删除调动记录"""
    transfers = load_transfer_data()
    
    for i, t in enumerate(transfers):
        if t['id'] == transfer_id:
            transfers.pop(i)
            save_transfer_data(transfers)
            return jsonify({'success': True})
    
    return jsonify({'error': '未找到调动记录'}), 404

@app.route('/api/personnel/<person_id>/transfers')
def get_person_transfers(person_id):
    """获取某人的调动历史"""
    transfers = load_transfer_data()
    person_transfers = [t for t in transfers if t['person_id'] == person_id]
    person_transfers.sort(key=lambda x: x.get('transfer_date', ''), reverse=True)
    
    return jsonify(person_transfers)

@app.route('/api/personnel/<person_id>/timeline')
def get_person_timeline(person_id):
    """获取某人的项目时间线（用于年终绩效计算）"""
    transfers = load_transfer_data()
    person_transfers = [t for t in transfers if t['person_id'] == person_id]
    person_transfers.sort(key=lambda x: x.get('transfer_date', ''))
    
    # 获取当前项目
    personnel = load_personnel_data()
    all_people = personnel['formal'] + personnel['outsourced']
    current_project = ''
    for p in all_people:
        if p['id'] == person_id:
            current_project = p.get('project', '未分配')
            break
    
    # 构建时间线
    timeline = []
    
    if not person_transfers:
        # 没有调动记录，当前项目就是全部
        timeline.append({
            'project': current_project,
            'start_date': '至今',
            'end_date': '至今',
            'months': 12  # 假设全年
        })
    else:
        # 有调动记录
        for i, t in enumerate(person_transfers):
            entry = {
                'project': t['to_project'],
                'start_date': t['transfer_date'],
                'end_date': person_transfers[i+1]['transfer_date'] if i+1 < len(person_transfers) else '至今'
            }
            # 计算月数
            try:
                start = datetime.strptime(t['transfer_date'], '%Y-%m-%d')
                if i+1 < len(person_transfers):
                    end = datetime.strptime(person_transfers[i+1]['transfer_date'], '%Y-%m-%d')
                else:
                    end = datetime.now()
                entry['months'] = (end.year - start.year) * 12 + end.month - start.month
            except:
                entry['months'] = 0
            
            timeline.append(entry)
        
        # 添加调动前的项目
        first_transfer = person_transfers[0]
        if first_transfer['from_project']:
            timeline.insert(0, {
                'project': first_transfer['from_project'],
                'start_date': '年初',
                'end_date': first_transfer['transfer_date'],
                'months': 0  # 需要根据具体日期计算
            })
    
    return jsonify({
        'person_id': person_id,
        'current_project': current_project,
        'timeline': timeline,
        'transfers': person_transfers
    })

# ============= 统计相关API =============


def map_edu_category(edu_str):
    """将学历映射到简化分类"""
    if not edu_str:
        return '未知'
    
    edu = str(edu_str).strip()
    
    # 本科类
    if any(keyword in edu for keyword in ['本科', '大学']):
        return '本科'
    
    # 专科类
    if any(keyword in edu for keyword in ['专科', '大专']):
        return '专科'
    
    # 高中及以下
    if any(keyword in edu for keyword in ['中专', '初中', '高中']):
        return '高中及以下'
    
    return '未知'

@app.route('/api/statistics')
def get_statistics():
    """获取统计数据"""
    data = load_personnel_data()
    
    stats = {
        'total': len(data['formal']) + len(data['outsourced']),
        'formal_count': len(data['formal']),
        'outsourced_count': len(data['outsourced']),
        'c1_count': len([p for p in data['outsourced'] if p['category'] == 'C1']),
        'c2_count': len([p for p in data['outsourced'] if p['category'] == 'C2']),
        'gender': {
            'male': len([p for p in data['formal'] + data['outsourced'] if p['gender'] == '男']),
            'female': len([p for p in data['formal'] + data['outsourced'] if p['gender'] == '女'])
        },
        'edu': {},
        'dept': {}
    }
    
    for p in data['formal'] + data['outsourced']:
        edu = p.get('edu', '未知')
        edu_category = map_edu_category(edu)
        stats['edu'][edu_category] = stats['edu'].get(edu_category, 0) + 1
    
    for p in data['formal']:
        dept = p.get('project', '未知')
        stats['dept'][dept] = stats['dept'].get(dept, 0) + 1
    
    return jsonify(stats)

@app.route('/api/export')
def export_excel():
    """导出Excel"""
    if os.path.exists(ROSTER_FILE):
        return send_file(ROSTER_FILE, as_attachment=True, download_name='安装公司人员花名册.xlsx')
    return jsonify({'error': '数据文件不存在'}), 404

@app.route('/api/export/transfers')
def export_transfers():
    """导出调动记录"""
    if os.path.exists(TRANSFER_FILE):
        return send_file(TRANSFER_FILE, as_attachment=True, download_name='人员调动记录.xlsx')
    return jsonify({'error': '调动记录文件不存在'}), 404

@app.route('/api/import', methods=['POST'])
def import_excel():
    """导入Excel数据"""
    if 'file' not in request.files:
        return jsonify({'error': '没有上传文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400
    
    if not file.filename.endswith('.xlsx'):
        return jsonify({'error': '请上传.xlsx格式的Excel文件'}), 400
    
    ensure_data_dir()
    file.save(ROSTER_FILE)
    
    return jsonify({'success': True, 'message': '导入成功'})

# ============= 状态管理API =============

@app.route('/api/personnel/<person_id>/status', methods=['PUT'])
def update_person_status(person_id):
    """更新人员状态"""
    data = request.json
    status_val = data.get('status', '在岗')
    detail = data.get('detail', '')
    
    # 保存到Excel
    wb = openpyxl.load_workbook(ROSTER_FILE)
    
    if person_id.startswith('F'):
        ws = wb['正式职工']
        row_idx = int(person_id[1:]) + 2
        if row_idx <= ws.max_row:
            ws.cell(row_idx, 12, status_val)
            ws.cell(row_idx, 13, detail)
    else:
        ws = wb['劳务外包人员']
        row_idx = int(person_id[1:]) + 2
        if row_idx <= ws.max_row:
            ws.cell(row_idx, 14, status_val)
            ws.cell(row_idx, 15, detail)
    
    wb.save(ROSTER_FILE)
    
    return jsonify({'success': True, 'status': {'status': status_val, 'detail': detail}})

# ============= 休假申请API =============

@app.route('/api/leave')
def get_leave_records():
    """获取休假申请列表"""
    records = load_leave_records()
    person_id = request.args.get('person_id')
    if person_id:
        records = [r for r in records if r['person_id'] == person_id]
    records.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return jsonify(records)

@app.route('/api/leave', methods=['POST'])
def add_leave():
    """新增休假申请"""
    data = request.json
    if not data.get('person_id') or not data.get('person_name'):
        return jsonify({'error': '人员信息不完整'}), 400
    if not data.get('start_date') or not data.get('end_date'):
        return jsonify({'error': '请选择休假时间'}), 400
    
    records = load_leave_records()
    new_record = {
        'id': f'L{len(records) + 1}',
        'person_id': data['person_id'],
        'person_name': data['person_name'],
        'start_date': data['start_date'],
        'end_date': data['end_date'],
        'reason': data.get('reason', ''),
        'status': '待审批',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    records.append(new_record)
    save_leave_records(records)
    return jsonify({'success': True, 'record': new_record})

@app.route('/api/leave/<record_id>/approve', methods=['PUT'])
def approve_leave(record_id):
    """审批休假申请"""
    records = load_leave_records()
    for i, r in enumerate(records):
        if r['id'] == record_id:
            records[i]['status'] = '已通过'
            save_leave_records(records)
            # 自动更新人员状态为休假
            person_id = r['person_id']
            wb = openpyxl.load_workbook(ROSTER_FILE)
            if person_id.startswith('F'):
                ws = wb['正式职工']
                row_idx = int(person_id[1:]) + 2
                if row_idx <= ws.max_row:
                    ws.cell(row_idx, 12, '休假')
                    ws.cell(row_idx, 13, f"休假至{r['end_date']}")
            else:
                ws = wb['劳务外包人员']
                row_idx = int(person_id[1:]) + 2
                if row_idx <= ws.max_row:
                    ws.cell(row_idx, 14, '休假')
                    ws.cell(row_idx, 15, f"休假至{r['end_date']}")
            wb.save(ROSTER_FILE)
            return jsonify({'success': True})
    return jsonify({'error': '未找到申请'}), 404

@app.route('/api/leave/<record_id>/reject', methods=['PUT'])
def reject_leave(record_id):
    """驳回休假申请"""
    records = load_leave_records()
    for i, r in enumerate(records):
        if r['id'] == record_id:
            records[i]['status'] = '已驳回'
            save_leave_records(records)
            return jsonify({'success': True})
    return jsonify({'error': '未找到申请'}), 404

# ============= 出差单API =============

@app.route('/api/trip')
def get_trip_records():
    """获取出差单列表"""
    records = load_trip_records()
    person_id = request.args.get('person_id')
    if person_id:
        records = [r for r in records if r['person_id'] == person_id]
    records.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return jsonify(records)

@app.route('/api/trip', methods=['POST'])
def add_trip():
    """新增出差单"""
    data = request.json
    if not data.get('person_id') or not data.get('person_name'):
        return jsonify({'error': '人员信息不完整'}), 400
    if not data.get('destination'):
        return jsonify({'error': '请填写出差目的地'}), 400
    if not data.get('start_date') or not data.get('end_date'):
        return jsonify({'error': '请选择出差时间'}), 400
    
    records = load_trip_records()
    new_record = {
        'id': f'B{len(records) + 1}',
        'person_id': data['person_id'],
        'person_name': data['person_name'],
        'destination': data['destination'],
        'start_date': data['start_date'],
        'end_date': data['end_date'],
        'reason': data.get('reason', ''),
        'status': '待审批',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    records.append(new_record)
    save_trip_records(records)
    return jsonify({'success': True, 'record': new_record})

@app.route('/api/trip/<record_id>/approve', methods=['PUT'])
def approve_trip(record_id):
    """审批出差"""
    records = load_trip_records()
    for i, r in enumerate(records):
        if r['id'] == record_id:
            records[i]['status'] = '已通过'
            save_trip_records(records)
            # 自动更新人员状态为出差
            person_id = r['person_id']
            wb = openpyxl.load_workbook(ROSTER_FILE)
            if person_id.startswith('F'):
                ws = wb['正式职工']
                row_idx = int(person_id[1:]) + 2
                if row_idx <= ws.max_row:
                    ws.cell(row_idx, 12, '出差')
                    ws.cell(row_idx, 13, f"出差-{r['destination']}")
            else:
                ws = wb['劳务外包人员']
                row_idx = int(person_id[1:]) + 2
                if row_idx <= ws.max_row:
                    ws.cell(row_idx, 14, '出差')
                    ws.cell(row_idx, 15, f"出差-{r['destination']}")
            wb.save(ROSTER_FILE)
            return jsonify({'success': True})
    return jsonify({'error': '未找到申请'}), 404

@app.route('/api/trip/<record_id>/reject', methods=['PUT'])
def reject_trip(record_id):
    """驳回出差"""
    records = load_trip_records()
    for i, r in enumerate(records):
        if r['id'] == record_id:
            records[i]['status'] = '已驳回'
            save_trip_records(records)
            return jsonify({'success': True})
    return jsonify({'error': '未找到申请'}), 404

# ============= 归队/销假API =============

@app.route('/api/personnel/<person_id>/return', methods=['PUT'])
def person_return(person_id):
    """人员归队/销假，恢复在岗状态"""
    wb = openpyxl.load_workbook(ROSTER_FILE)
    
    if person_id.startswith('F'):
        ws = wb['正式职工']
        row_idx = int(person_id[1:]) + 2
        if row_idx <= ws.max_row:
            ws.cell(row_idx, 12, '在岗')
            ws.cell(row_idx, 13, '')
    else:
        ws = wb['劳务外包人员']
        row_idx = int(person_id[1:]) + 2
        if row_idx <= ws.max_row:
            ws.cell(row_idx, 14, '在岗')
            ws.cell(row_idx, 15, '')
    
    wb.save(ROSTER_FILE)
    return jsonify({'success': True})

# ============= 登录API =============

import hashlib

@app.route('/api/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.json
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()

    if not phone or not password:
        return jsonify({'error': '手机号和密码不能为空'}), 400

    users = load_users()
    user = users.get(phone)

    if not user:
        return jsonify({'error': '用户不存在'}), 401

    if user['password'] != password:
        return jsonify({'error': '密码错误'}), 401

    # 生成简单token
    token = hashlib.md5(f"{phone}:{password}:{datetime.now().date()}".encode()).hexdigest()

    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'phone': user['phone'],
            'name': user['name'],
            'is_admin': user.get('is_admin', False)
        }
    })

@app.route('/api/users', methods=['GET'])
def get_users():
    """获取用户列表（管理员）"""
    users = load_users()
    result = []
    for phone, user in users.items():
        result.append({
            'phone': user['phone'],
            'name': user['name'],
            'is_admin': user.get('is_admin', False)
        })
    return jsonify(result)

@app.route('/api/users', methods=['POST'])
def add_user():
    """添加用户（管理员）"""
    data = request.json
    phone = data.get('phone', '').strip()
    name = data.get('name', '').strip()
    password = data.get('password', '123456')
    is_admin = data.get('is_admin', False)

    if not phone or not name:
        return jsonify({'error': '手机号和姓名不能为空'}), 400

    users = load_users()
    if phone in users:
        return jsonify({'error': '用户已存在'}), 400

    users[phone] = {
        'phone': phone,
        'name': name,
        'password': password,
        'is_admin': is_admin
    }
    save_users(users)

    return jsonify({'success': True})

if __name__ == '__main__':
    ensure_data_dir()
    print("=" * 50)
    print("安装公司人员信息管理系统")
    print("=" * 50)
    print("访问地址: http://localhost:5000")
    print("按 Ctrl+C 退出")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)
