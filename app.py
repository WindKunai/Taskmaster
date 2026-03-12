import os
import json
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, date

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = os.environ.get('SQLALCHEMY_TRACK_MODIFICATIONS')

db = SQLAlchemy(app)


# ── Models ────────────────────────────────────────────────────────────────────

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    done = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    due_date = db.Column(db.Date, nullable=True)

    task_list = db.relationship('TaskList', back_populates='task',
                                uselist=False, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Task {self.id}: {self.title}>'


class TaskList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False, unique=True)

    task = db.relationship('Task', back_populates='task_list')
    items = db.relationship('TaskListItem', back_populates='task_list',
                            order_by='TaskListItem.position',
                            cascade='all, delete-orphan')


class TaskListItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey('task_list.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    text = db.Column(db.String(500), nullable=False)
    completed = db.Column(db.Boolean, default=False)

    task_list = db.relationship('TaskList', back_populates='items')


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_due_date(value: str):
    """Return a date object from an ISO string, or None if blank/invalid."""
    value = (value or '').strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def save_list_items(task, items_json: str):
    """Parse JSON list items and attach them to a task, replacing any existing list."""
    try:
        items = json.loads(items_json or '[]')
    except (ValueError, TypeError):
        items = []

    if not isinstance(items, list):
        return

    if task.task_list:
        db.session.delete(task.task_list)
        db.session.flush()

    if not items:
        return

    task_list = TaskList(task=task)
    db.session.add(task_list)

    for pos, item in enumerate(items):
        text = (item.get('text') or '').strip()
        if text:
            db.session.add(TaskListItem(
                task_list=task_list,
                position=pos,
                text=text,
                completed=bool(item.get('completed', False)),
            ))


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    filter_by = request.args.get('filter', 'all')
    if filter_by == 'active':
        tasks = Task.query.filter_by(done=False).order_by(Task.created_at.desc()).all()
    elif filter_by == 'done':
        tasks = Task.query.filter_by(done=True).order_by(Task.created_at.desc()).all()
    else:
        tasks = Task.query.order_by(Task.created_at.desc()).all()
    total = Task.query.count()
    done_count = Task.query.filter_by(done=True).count()
    today = date.today()
    return render_template('index.html', tasks=tasks, filter_by=filter_by,
                           total=total, done_count=done_count, today=today)


@app.route('/add', methods=['GET', 'POST'])
def add_task():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        content_type = request.form.get('content_type', 'text')

        if not title:
            flash('Task title is required.', 'error')
            return render_template('add_task.html')

        task = Task(
            title=title,
            description=description if content_type == 'text' else '',
            due_date=parse_due_date(request.form.get('due_date')),
        )
        db.session.add(task)
        db.session.flush()

        if content_type == 'list':
            save_list_items(task, request.form.get('list_items', '[]'))

        db.session.commit()
        flash('Task added successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('add_task.html')


@app.route('/edit/<int:task_id>', methods=['GET', 'POST'])
def edit_task(task_id):
    task = db.get_or_404(Task, task_id)
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        content_type = request.form.get('content_type', 'text')

        if not title:
            flash('Task title is required.', 'error')
            return render_template('edit_task.html', task=task)

        task.title = title
        task.due_date = parse_due_date(request.form.get('due_date'))

        if content_type == 'text':
            task.description = description
            if task.task_list:
                db.session.delete(task.task_list)
        else:
            task.description = ''
            save_list_items(task, request.form.get('list_items', '[]'))

        db.session.commit()
        flash('Task updated successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('edit_task.html', task=task)


@app.route('/toggle/<int:task_id>', methods=['POST'])
def toggle_task(task_id):
    task = db.get_or_404(Task, task_id)
    task.done = not task.done
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/toggle_item/<int:item_id>', methods=['POST'])
def toggle_item(item_id):
    item = db.get_or_404(TaskListItem, item_id)
    item.completed = not item.completed
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/remove_due_date/<int:task_id>', methods=['POST'])
def remove_due_date(task_id):
    task = db.get_or_404(Task, task_id)
    task.due_date = None
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/delete/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    task = db.get_or_404(Task, task_id)
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted.', 'success')
    return redirect(url_for('index'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')