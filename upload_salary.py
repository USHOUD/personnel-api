#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人事令PDF上传解析接口"""

from flask import Blueprint, request, jsonify
import fitz
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from supabase_config import get_db
import tempfile
import os

upload_bp = Blueprint('upload', __name__)

@upload_bp.route('/api/upload-order', methods=['POST'])
def upload_order():
    """上传人事令PDF，自动识别工资信息"""
    # Check if file is in request
    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400
    
    file = request.files['file']
    if not file.filename or not file.filename.endswith('.pdf'):
        return jsonify({'error': '只支持PDF文件'}), 400
    
    try:
        # Save file to temp directory
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, file.filename)
        file.save(temp_path)
        
        # Read PDF
        doc = fitz.open(temp_path)
        
        results = []
        for page in doc:
            text = page.get_text()
            parsed = parse_salary_table(text)
            results.extend(parsed)
        
        doc.close()
        
        # Clean up temp file
        os.remove(temp_path)
        os.rmdir(temp_dir)
        
        # Match with database
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        matched = []
        unmatched = []
        
        for item in results:
            cur.execute("""
                SELECT id, name, position, project, category, salary
                FROM personnel
                WHERE name = %s AND status = '在岗'
            """, (item['name'],))
            
            db_record = cur.fetchone()
            
            if db_record:
                matched.append({
                    'name': item['name'],
                    'position': item['position'],
                    'base_salary': item['base_salary'],
                    'edu_salary': item['edu_salary'],
                    'skill_salary': item['skill_salary'],
                    'seniority_salary': item['seniority_salary'],
                    'total_salary': item['total_salary'],
                    'db_id': db_record['id'],
                    'db_position': db_record['position'],
                    'db_project': db_record['project'],
                    'db_category': db_record['category'],
                    'db_salary': float(db_record['salary']) if db_record['salary'] else None
                })
            else:
                unmatched.append(item)
        
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'total_parsed': len(results),
            'matched': len(matched),
            'unmatched': len(unmatched),
            'data': matched,
            'unmatched_names': [u['name'] for u in unmatched]
        })
        
    except Exception as e:
        return jsonify({'error': f'解析失败: {str(e)}'}), 500


@upload_bp.route('/api/update-salary', methods=['POST'])
def update_salary():
    """确认后批量更新工资"""
    data = request.json
    updates = data.get('updates', [])
    
    if not updates:
        return jsonify({'error': '无更新数据'}), 400
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        updated = []
        for item in updates:
            person_id = item.get('db_id')
            salary = item.get('total_salary')
            
            if person_id and salary:
                cur.execute("""
                    UPDATE personnel 
                    SET salary = %s, updated_at = NOW()
                    WHERE id = %s
                """, (salary, person_id))
                
                if cur.rowcount > 0:
                    updated.append(item['name'])
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'updated': len(updated),
            'names': updated
        })
        
    except Exception as e:
        return jsonify({'error': f'更新失败: {str(e)}'}), 500


def parse_salary_table(text):
    """解析工资表格"""
    lines = text.split('\n')
    data = []
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        # Look for pattern: number, name, position, salary components
        if re.match(r'^\d+$', line) and i + 7 < len(lines):
            seq = int(line)
            name = lines[i+1].strip()
            position = lines[i+2].strip()
            
            try:
                base_salary = int(lines[i+3].strip())
                edu_salary = int(lines[i+4].strip())
                skill_salary = int(lines[i+5].strip())
                seniority_salary = int(lines[i+6].strip())
                min_guarantee = int(lines[i+7].strip())
                
                total_salary = base_salary + edu_salary + skill_salary + seniority_salary
                
                data.append({
                    'name': name,
                    'position': position,
                    'base_salary': base_salary,
                    'edu_salary': edu_salary,
                    'skill_salary': skill_salary,
                    'seniority_salary': seniority_salary,
                    'min_guarantee': min_guarantee,
                    'total_salary': total_salary
                })
                i += 8
                continue
            except (ValueError, IndexError):
                pass
        i += 1
    
    return data
