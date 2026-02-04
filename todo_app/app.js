const form = document.getElementById('todo-form');
const input = document.getElementById('todo-input');
const list = document.getElementById('todo-list');
const clearBtn = document.getElementById('clear-completed');
const countSpan = document.getElementById('count');

let todos = [];

function save() {
  localStorage.setItem('todos', JSON.stringify(todos));
}

function load() {
  const raw = localStorage.getItem('todos');
  todos = raw ? JSON.parse(raw) : [];
}

function render() {
  list.innerHTML = '';
  todos.forEach((t, i) => {
    const li = document.createElement('li');
    li.className = 'todo-item';

    const chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.checked = t.done;
    chk.addEventListener('change', () => {
      todos[i].done = chk.checked;
      save();
      render();
    });

    const span = document.createElement('span');
    span.className = 'label';
    span.textContent = t.text;
    if (t.done) span.classList.add('done');
    span.contentEditable = true;
    span.addEventListener('blur', () => {
      const text = span.textContent.trim();
      if (text) {
        todos[i].text = text;
        save();
      } else {
        // if emptied, remove
        todos.splice(i, 1);
        save();
        render();
      }
    });

    const del = document.createElement('button');
    del.className = 'delete';
    del.textContent = '✕';
    del.title = 'Delete';
    del.addEventListener('click', () => {
      todos.splice(i, 1);
      save();
      render();
    });

    li.appendChild(chk);
    li.appendChild(span);
    li.appendChild(del);
    list.appendChild(li);
  });

  const remaining = todos.filter(t => !t.done).length;
  countSpan.textContent = `${remaining} remaining`;
}

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  todos.push({ text, done: false });
  input.value = '';
  save();
  render();
});

clearBtn.addEventListener('click', () => {
  todos = todos.filter(t => !t.done);
  save();
  render();
});

// init
load();
render();