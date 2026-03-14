import os
import json
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, date, timedelta

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = os.environ.get('SQLALCHEMY_TRACK_MODIFICATIONS')

db = SQLAlchemy(app)


# ── Models ────────────────────────────────────────────────────────────────────

# Association table: many tasks <-> many categories
task_categories = db.Table(
    'task_categories',
    db.Column('task_id', db.Integer, db.ForeignKey('task.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('category.id'), primary_key=True),
)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    color = db.Column(db.String(7), nullable=False, default='#8a8680')  # hex

    def __repr__(self):
        return f'<Category {self.name}>'


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    done = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    due_date = db.Column(db.Date, nullable=True)

    task_list = db.relationship('TaskList', back_populates='task',
                                uselist=False, cascade='all, delete-orphan')
    categories = db.relationship('Category', secondary=task_categories,
                                 backref='tasks', lazy='subquery')

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
    value = (value or '').strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def save_list_items(task, items_json: str):
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


def resolve_categories(cat_ids: list[str]) -> list[Category]:
    """Return Category objects for a list of id strings, ignoring invalid ones."""
    cats = []
    for cid in cat_ids:
        try:
            cat = db.session.get(Category, int(cid))
            if cat:
                cats.append(cat)
        except (ValueError, TypeError):
            pass
    return cats


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    filter_by = request.args.get('filter', 'active')   # default: active
    sort_by = request.args.get('sort', 'due')           # default: due date
    cat_filter = request.args.get('cat', '')            # category id or ''

    query = Task.query
    if filter_by == 'active':
        query = query.filter_by(done=False)
    elif filter_by == 'done':
        query = query.filter_by(done=True)

    if cat_filter:
        try:
            query = query.filter(Task.categories.any(Category.id == int(cat_filter)))
        except (ValueError, TypeError):
            cat_filter = ''

    if sort_by == 'due':
        query = query.order_by(Task.due_date.is_(None), Task.due_date.asc())
    elif sort_by == 'title':
        query = query.order_by(Task.title.asc())
    else:
        query = query.order_by(Task.created_at.desc())

    tasks = query.all()
    total = Task.query.count()
    done_count = Task.query.filter_by(done=True).count()
    today = date.today()

    month_start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
    month_count = Task.query.filter(
        Task.done == True,
        Task.created_at >= month_start,
    ).count()

    overdue_count = Task.query.filter(
        Task.done == False,
        Task.due_date < today,
        Task.due_date.isnot(None),
    ).count()

    all_categories = Category.query.order_by(Category.name).all()

    return render_template('index.html', tasks=tasks, filter_by=filter_by,
                           sort_by=sort_by, cat_filter=cat_filter,
                           total=total, done_count=done_count,
                           today=today, month_count=month_count,
                           overdue_count=overdue_count,
                           all_categories=all_categories)


@app.route('/add', methods=['GET', 'POST'])
def add_task():
    all_categories = Category.query.order_by(Category.name).all()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        content_type = request.form.get('content_type', 'text')
        if not title:
            flash('Task title is required.', 'error')
            return render_template('add_task.html', all_categories=all_categories)
        task = Task(
            title=title,
            description=description if content_type == 'text' else '',
            due_date=parse_due_date(request.form.get('due_date')),
        )
        task.categories = resolve_categories(request.form.getlist('categories'))
        db.session.add(task)
        db.session.flush()
        if content_type == 'list':
            save_list_items(task, request.form.get('list_items', '[]'))
        db.session.commit()
        flash('Task added.', 'success')
        return redirect(url_for('index'))
    return render_template('add_task.html', all_categories=all_categories)


@app.route('/edit/<int:task_id>', methods=['GET', 'POST'])
def edit_task(task_id):
    task = db.get_or_404(Task, task_id)
    all_categories = Category.query.order_by(Category.name).all()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        content_type = request.form.get('content_type', 'text')
        if not title:
            flash('Task title is required.', 'error')
            return render_template('edit_task.html', task=task, all_categories=all_categories)
        task.title = title
        task.due_date = parse_due_date(request.form.get('due_date'))
        task.categories = resolve_categories(request.form.getlist('categories'))
        if content_type == 'text':
            task.description = description
            if task.task_list:
                db.session.delete(task.task_list)
        else:
            task.description = ''
            save_list_items(task, request.form.get('list_items', '[]'))
        db.session.commit()
        flash('Task updated.', 'success')
        return redirect(url_for('index'))
    return render_template('edit_task.html', task=task, all_categories=all_categories)


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


# ── Category management ───────────────────────────────────────────────────────

@app.route('/categories', methods=['GET', 'POST'])
def manage_categories():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name', '').strip()
            color = request.form.get('color', '#8a8680').strip()
            if name:
                if Category.query.filter_by(name=name).first():
                    flash('Category already exists.', 'error')
                else:
                    db.session.add(Category(name=name, color=color))
                    db.session.commit()
                    flash(f'Category "{name}" added.', 'success')
            else:
                flash('Category name is required.', 'error')
        elif action == 'delete':
            cat_id = request.form.get('cat_id')
            cat = db.get_or_404(Category, cat_id)
            db.session.delete(cat)
            db.session.commit()
            flash(f'Category "{cat.name}" deleted.', 'success')
        return redirect(url_for('manage_categories'))
    categories = Category.query.order_by(Category.name).all()
    return render_template('categories.html', categories=categories)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')
