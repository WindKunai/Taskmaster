import pytest
from app import app, db, Task


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            yield client
            db.drop_all()


def test_index_empty(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'My Tasks' in response.data


def test_add_task(client):
    response = client.post('/add', data={'title': 'Buy groceries', 'description': 'Milk and eggs'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Buy groceries' in response.data
    assert b'Task added successfully!' in response.data


def test_add_task_empty_title(client):
    response = client.post('/add', data={'title': '', 'description': 'No title'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Task title is required.' in response.data


def test_index_shows_tasks(client):
    with app.app_context():
        task = Task(title='Write tests', description='Cover all routes')
        db.session.add(task)
        db.session.commit()
    response = client.get('/')
    assert b'Write tests' in response.data


def test_toggle_task(client):
    with app.app_context():
        task = Task(title='Toggle me')
        db.session.add(task)
        db.session.commit()
        task_id = task.id

    response = client.post(f'/toggle/{task_id}', follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        updated = db.session.get(Task, task_id)
        assert updated.done is True

    # Toggle back
    client.post(f'/toggle/{task_id}')
    with app.app_context():
        updated = db.session.get(Task, task_id)
        assert updated.done is False


def test_edit_task(client):
    with app.app_context():
        task = Task(title='Old title')
        db.session.add(task)
        db.session.commit()
        task_id = task.id

    response = client.get(f'/edit/{task_id}')
    assert response.status_code == 200
    assert b'Old title' in response.data

    response = client.post(f'/edit/{task_id}', data={'title': 'New title', 'description': 'Updated'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'New title' in response.data
    assert b'Task updated successfully!' in response.data


def test_edit_task_empty_title(client):
    with app.app_context():
        task = Task(title='Original')
        db.session.add(task)
        db.session.commit()
        task_id = task.id

    response = client.post(f'/edit/{task_id}', data={'title': '', 'description': ''}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Task title is required.' in response.data


def test_delete_task(client):
    with app.app_context():
        task = Task(title='Delete me')
        db.session.add(task)
        db.session.commit()
        task_id = task.id

    response = client.post(f'/delete/{task_id}', follow_redirects=True)
    assert response.status_code == 200
    assert b'Delete me' not in response.data
    assert b'Task deleted.' in response.data


def test_filter_active(client):
    with app.app_context():
        db.session.add(Task(title='Active task', done=False))
        db.session.add(Task(title='Done task', done=True))
        db.session.commit()

    response = client.get('/?filter=active')
    assert b'Active task' in response.data
    assert b'Done task' not in response.data


def test_filter_done(client):
    with app.app_context():
        db.session.add(Task(title='Active task', done=False))
        db.session.add(Task(title='Done task', done=True))
        db.session.commit()

    response = client.get('/?filter=done')
    assert b'Done task' in response.data
    assert b'Active task' not in response.data


def test_404_edit_nonexistent(client):
    response = client.get('/edit/9999')
    assert response.status_code == 404


def test_404_delete_nonexistent(client):
    response = client.post('/delete/9999')
    assert response.status_code == 404
