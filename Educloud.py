
import sys
import openai
import os
import json
import re
import asyncio
import qasync
from PyQt6.QtGui import (QFont, QColor, QDesktopServices, QIcon, QPixmap, QCursor, QMovie)
from PyQt6.QtCore import Qt, QUrl, QPropertyAnimation, QEasingCurve, pyqtSignal, QPoint, QDate
from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QCheckBox, QGraphicsDropShadowEffect, QStackedWidget,
                             QScrollArea, QFrame, QListWidget, QListWidgetItem, QCalendarWidget,
                             QTabWidget, QInputDialog, QComboBox, QSizePolicy, QTextEdit,
                             QDialog, QFileDialog, QMessageBox, QProgressDialog)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import httpx
from datetime import datetime

# --- Supabase Configuration ---
SUPABASE_URL = "https://mpfandlcszripdcdzfkm.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1wZmFuZGxjc3pyaXBkY2R6ZmttIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTA1Nzk1OTgsImV4cCI6MjA2NjE1NTU5OH0.qNWmkzWC4xMDk00fDUnJH869N_wLd_Txx38XWpWaaJQ"
SUPABASE_BUCKET_NAME = "files"

if SUPABASE_URL.endswith('/'):
    SUPABASE_URL = SUPABASE_URL[:-1]

class SupabaseDBClient:
    def __init__(self, base_url, anon_key):
        self.base_url = base_url
        self.anon_key = anon_key
        self.headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    async def select_records(self, table_name, filters=None, order_by=None, limit=None):
        try:
            # Corrected column selection for 'group_files' to use 'file_id,*'
            # as per the provided database schema, resolving the 'column group_files.id does not exist' error.
            if table_name == "groups":
                select_columns = "*" # 'groups' table uses 'group_id' as primary key
            elif table_name == "group_files":
                select_columns = "file_id,*" # 'group_files' uses 'file_id' as primary key
            elif table_name in ["group_members", "students"]:
                select_columns = "id,*" # These tables use 'id' as primary key
            else:
                select_columns = "*" # Default for other tables

            url = f"{self.base_url}/rest/v1/{table_name}?select={select_columns}"
            if filters:
                filter_params = []
                for column, operator, value in filters:
                    filter_params.append(f"{column}={operator}.{value}")
                url += "&" + '&'.join(filter_params)
            if order_by:
                url += f"&order={order_by}"
            if limit is not None:
                url += f"&limit={limit}"

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.headers, timeout=10)
                response.raise_for_status()
                return response.json(), None # Return data and no error
        except httpx.HTTPStatusError as e:
            return [], f"HTTP error selecting from {table_name}: {e.response.status_code} - {e.response.text}"
        except httpx.RequestError as e:
            return [], f"Network error selecting from {table_name}: {e}"
        except Exception as e:
            return [], f"An unexpected error occurred selecting from {table_name}: {e}"

    async def insert_record(self, table_name, data):
        try:
            url = f"{self.base_url}/rest/v1/{table_name}"
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=self.headers, json=data, timeout=10)
                response.raise_for_status()

                if response.status_code == 201 and not response.text.strip():
                    return {}, None # Success, no content
                elif response.status_code == 204:
                    return {}, None # Success, no content
                elif response.status_code == 201 and response.text.strip():
                    return response.json(), None # Success, with content
                else:
                    return None, f"Insert into {table_name} succeeded but returned no content or unexpected content. Status: {response.status_code}"

        except httpx.HTTPStatusError as e:
            return None, f"HTTP error inserting into {table_name}: {e.response.status_code} - {e.response.text}"
        except httpx.RequestError as e:
            return None, f"Network error inserting into {table_name}: {e}"
        except json.JSONDecodeError as e:
            return None, f"Failed to parse JSON response inserting into {table_name}: {e}. Response: {response.text}"
        except Exception as e:
            return None, f"An unexpected error occurred inserting into {table_name}: {e}"

    async def delete_records(self, table_name, filters):
        try:
            url = f"{self.base_url}/rest/v1/{table_name}"
            if filters:
                filter_params = []
                for column, operator, value in filters:
                    filter_params.append(f"{column}={operator}.{value}")
                url += "?" + '&'.join(filter_params)

            async with httpx.AsyncClient() as client:
                response = await client.delete(url, headers=self.headers, timeout=10)
                response.raise_for_status()
                return True, None # Success, no error
        except httpx.HTTPStatusError as e:
            return False, f"HTTP error deleting from {table_name}: {e.response.status_code} - {e.response.text}\nFull response: {e.response.text}"
        except httpx.RequestError as e:
            return False, f"Network error deleting from {table_name}: {e}"
        except Exception as e:
            return False, f"An unexpected error occurred deleting from {table_name}: {e}"


supabase_db_client = SupabaseDBClient(SUPABASE_URL, SUPABASE_ANON_KEY)

class SupabaseStorageManager:
    def __init__(self, base_url, anon_key, bucket_name):
        self.base_url = base_url
        self.anon_key = anon_key
        self.bucket_name = bucket_name
        self.headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}"
        }

    def _get_storage_url(self, path=""):
        return f"{self.base_url}/storage/v1/object/public/{self.bucket_name}/{path}"

    def _get_upload_url(self, path):
        return f"{self.base_url}/storage/v1/object/{self.bucket_name}/{path}"

    # Added this method to allow viewing of files
    def get_file_public_url(self, file_path_in_bucket):
        """Constructs the public URL for a file in Supabase Storage."""
        # Ensure the path is correct after the bucket name
        if file_path_in_bucket.startswith(f"{self.bucket_name}/"):
            relative_path = file_path_in_bucket
        else:
            # Assume file_path_in_bucket is already the full path within the bucket
            relative_path = file_path_in_bucket
        return self._get_storage_url(relative_path)

    async def upload_file(self, local_file_path, destination_file_name):
        try:
            with open(local_file_path, 'rb') as f:
                file_content = f.read()

            upload_headers = self.headers.copy()
            content_type = "application/octet-stream"
            if destination_file_name.lower().endswith(".pdf"):
                content_type = "application/pdf"
            elif destination_file_name.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                content_type = "image/jpeg"
            elif destination_file_name.lower().endswith(".txt"):
                content_type = "text/plain"
            upload_headers["Content-Type"] = content_type

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._get_upload_url(destination_file_name),
                    headers=upload_headers,
                    content=file_content,
                    timeout=60
                )
                response.raise_for_status()
                return True, None # Success, no error
        except httpx.HTTPStatusError as e:
            return False, f"HTTP Error: {e.response.status_code} - {e.response.text}"
        except httpx.RequestError as e:
            return False, f"Request Error: {e}"
        except Exception as e:
            return False, f"An unexpected error occurred: {e}"

    async def delete_file(self, file_path_in_bucket):
        try:
            delete_url = f"{self.base_url}/storage/v1/object/{self.bucket_name}"
            async with httpx.AsyncClient() as client:
                payload = {"prefixes": [file_path_in_bucket]}
                encoded_payload = json.dumps(payload).encode('utf-8')

                response = await client.request(
                    "DELETE",
                    delete_url,
                    headers={
                        "apikey": self.anon_key,
                        "Authorization": f"Bearer {self.anon_key}",
                        "Content-Type": "application/json" # Crucial for Supabase to parse the body
                    },
                    content=encoded_payload, # Pass as raw content
                    timeout=10
                )
                response.raise_for_status()
                return True, None # Success, no error
        except httpx.HTTPStatusError as e:
            # Print full response text for more detailed error from Supabase
            return False, f"HTTP error deleting file: {e.response.status_code} - {e.response.text}\nFull response: {e.response.text}\nEnsure your Supabase Storage policies allow DELETE operations for the 'anon' role or the authenticated user."
        except httpx.RequestError as e:
            return False, f"Network error deleting file: {e}"
        except Exception as e:
            return False, f"An unexpected error occurred deleting file: {e}"


supabase_storage = SupabaseStorageManager(SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_BUCKET_NAME)

openai.api_key = "your_api_key_here"

STYLESHEET = """
    QWidget {
        background-color: #f9fafb;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 13px;
        color: #2e343b;
    }
    QPushButton {
        background-color: #3b82f6;
        color: white;
        padding: 10px 16px;
        border-radius: 10px;
        font-weight: 600;
        border: none;
    }
    QPushButton:hover {
        background-color: #2563eb;
    }
    QPushButton:pressed {
        background-color: #1d4ed8;
    }
    QPushButton:disabled {
        background-color: #9ca3af;
        color: #d1d5db;
    }
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
        border: 1.5px solid #d1d5db;
        border-radius: 8px;
        padding: 8px;
        background-color: white;
        font-size: 14px;
        selection-background-color: #60a5fa;
        selection-color: white;
    }
    QLineEdit:hover, QTextEdit:hover, QComboBox:hover {
        border-color: #3b82f6;
    }
    QListWidget {
        background-color: white;
        border: 1.5px solid #d1d5db;
        padding: 6px;
        border-radius: 8px;
    }
    QTabWidget::pane {
        border: 1.5px solid #cbd5e1;
        background: white;
        border-radius: 8px;
    }
    QTabBar::tab {
        background: #e0e7ff;
        padding: 10px 16px;
        border-radius: 8px 8px 0 0;
        margin-right: 4px;
        font-weight: 600;
        color: #374151;
    }
    QTabBar::tab:selected {
        background: #6366f1;
        color: white;
    }
    QLabel {
        font-size: 14px;
        color: #1f2937;
    }
    QCheckBox {
        font-size: 14px;
    }
    QCalendarWidget QWidget {
        font-size: 14px;
    }
"""

FLOATING_SUBJECT_STYLE = """
    QPushButton {
        background-color: rgba(255, 255, 255, 0.95);
        border: 1.2px solid #d1d5db;
        border-radius: 14px;
        padding: 18px;
        font-size: 17px;
        color: #111827;
    }
    QPushButton:hover {
        background-color: #f3f4f6;
    }
"""


def get_ai_response(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response['choices'][0]['message']['content']


NOTES_FILE = "notes.json"
ASSIGNMENTS_FILE = "assignment_submissions.json"

if os.path.exists(NOTES_FILE):
    try:
        with open(NOTES_FILE, "r") as f:
            SAVED_NOTES = json.load(f)
    except Exception as e:
        SAVED_NOTES = {}
else:
    SAVED_NOTES = {}

if os.path.exists(ASSIGNMENTS_FILE):
    try:
        with open(ASSIGNMENTS_FILE, "r") as f:
            SUBMITTED_ASSIGNMENTS = json.load(f)
    except Exception as e:
        SUBMITTED_ASSIGNMENTS = {}
else:
    SUBMITTED_ASSIGNMENTS = {}

progress_data = {
    "This Week": [
        ("Math Homework", "Graded: 90/100", "green"),
        ("Science Quiz", "Ungraded", "gray"),
        ("English Essay", "Graded: 88/100", "green"),
        ("History Quiz", "Graded: 82/100", "green"),
        ("Biology Lab", "Ungraded", "gray"),
        ("PE Fitness Test", "Graded: 92/100", "green"),
        ("Computer Assignment", "Graded: 85/100", "green")
    ]
}

GROUPS_FILE = "groups.json"
if os.path.exists(GROUPS_FILE):
    try:
        with open(GROUPS_FILE, "r") as f:
            GROUPS_DATA = json.load(f)
    except:
        GROUPS_DATA = {}
else:
    GROUPS_DATA = {}

class TaskDialog(QDialog):
    def __init__(self, parent=None, task=None):
        super().__init__(parent)
        self.setWindowTitle("Task Details")
        self.setFixedSize(400, 520)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Task Title:"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Task Title")
        layout.addWidget(self.title_edit)

        layout.addWidget(QLabel("Due Date:"))
        self.date_edit = QCalendarWidget()
        self.date_edit.setFixedHeight(200)
        self.date_edit.setStyleSheet("""
            QCalendarWidget QAbstractItemView {
                font-size: 13px;
                selection-background-color: #3b82f6;
                selection-color: white;
                gridline-color: #e5e7eb;
            }
            QCalendarWidget QToolButton {
                font-size: 14px;
                color: #1e3a8a;
            }
            QCalendarWidget QHeaderView::section {
                font-weight: bold;
                color: #374151;
                background-color: #f3f4f6;
            }
        """)

        self.date_edit.setGridVisible(True)
        layout.addWidget(self.date_edit)

        layout.addWidget(QLabel("Description:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Task Description (Optional)")
        self.desc_edit.setFixedHeight(80)
        layout.addWidget(self.desc_edit)

        self.completed_checkbox = QCheckBox("Completed")
        layout.addWidget(self.completed_checkbox)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        ok_btn.clicked.connect(self.validate_and_accept)
        cancel_btn.clicked.connect(self.reject)

        if task:
            self.title_edit.setText(task.get("title", ""))
            due = task.get("due_date")
            if isinstance(due, QDate):
                self.date_edit.setSelectedDate(due)
            elif isinstance(due, str):
                dt = QDate.fromString(due, "yyyy-MM-dd")
                if dt.isValid():
                    self.date_edit.setSelectedDate(dt)
            self.desc_edit.setPlainText(task.get("description", ""))
            self.completed_checkbox.setChecked(task.get("completed", False))

    def validate_and_accept(self):
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "Input Error", "Task Title cannot be empty.")
        else:
            self.accept()

    def get_task_data(self):
        return {
            "title": self.title_edit.text().strip(),
            "due_date": self.date_edit.selectedDate(),
            "description": self.desc_edit.toPlainText().strip(),
            "completed": self.completed_checkbox.isChecked()
        }

class ToDoWidget(QWidget):
    def __init__(self, shared_tasks, on_tasks_updated):
        super().__init__()
        self.tasks = shared_tasks
        self.on_tasks_updated = on_tasks_updated

        main_layout = QVBoxLayout(self)

        title = QLabel("Today's Tasks")
        title.setFont(QFont("Segoe UI Semibold", 20))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        self.task_list = QListWidget()
        self.task_list.setFont(QFont("Segoe UI", 14))
        main_layout.addWidget(self.task_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add Task")
        add_btn.setFont(QFont("Segoe UI Semibold", 14))
        add_btn.clicked.connect(self.add_task)
        btn_layout.addWidget(add_btn)

        edit_btn = QPushButton("Edit Selected Task")
        edit_btn.setFont(QFont("Segoe UI Semibold", 14))
        edit_btn.clicked.connect(self.edit_task)
        btn_layout.addWidget(edit_btn)

        del_btn = QPushButton("Delete Selected Task")
        del_btn.setFont(QFont("Segoe UI Semibold", 14))
        del_btn.clicked.connect(self.delete_task)
        btn_layout.addWidget(del_btn)

        main_layout.addLayout(btn_layout)

        self.refresh_task_list()

    def refresh_task_list(self):
        self.task_list.clear()
        for task in self.tasks:
            status = "✓ " if task["completed"] else "✗ "
            due_date = task.get("due_date")
            due_str = due_date.toString("yyyy-MM-dd") if isinstance(due_date, QDate) else "No due date"
            item_text = f"{status}{task['title']} – Due: {due_str}"
            item = QListWidgetItem(item_text)
            item.setForeground(QColor("green") if task["completed"] else QColor("black"))
            self.task_list.addItem(item)

    def add_task(self):
        try:
            dialog = TaskDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.tasks.append(dialog.get_task_data())
                self.refresh_task_list()
                self.on_tasks_updated()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add task:\n{e}")

    def edit_task(self):
        try:
            selected_items = self.task_list.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "No Selection", "Please select a task to edit.")
                return
            idx = self.task_list.currentRow()
            task = self.tasks[idx]
            dialog = TaskDialog(self, task)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.tasks[idx] = dialog.get_task_data()
                self.refresh_task_list()
                self.on_tasks_updated()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to edit task:\n{e}")

    def delete_task(self):
        try:
            selected_items = self.task_list.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "No Selection", "Please select a task to delete.")
                return
            idx = self.task_list.currentRow()
            task_title = self.tasks[idx]["title"]
            confirm = QMessageBox.question(
                self,
                "Delete Task",
                f"Are you sure you want to delete '{task_title}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm == QMessageBox.StandardButton.Yes:
                self.tasks.pop(idx)
                self.refresh_task_list()
                self.on_tasks_updated()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete task:\n{e}")


class SubjectDetailPage(QWidget):
    def __init__(self, subject_name, back_callback):
        super().__init__()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        main_container = QWidget()
        main_layout = QVBoxLayout(main_container)
        main_layout.setSpacing(24)
        main_layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel(f"{subject_name} Details")
        title.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #4f46e5;")
        main_layout.addWidget(title)

        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("QTabWidget::pane { border: none; }")

        section_data = [
            ("Modules", "modules", [
                ("Module 1: Introduction", "Mathematics is the study of numbers, shapes, and patterns."),
                ("Module 2: Advanced Topics", "Covers calculus and problem-solving techniques."),
                ("Module 3: Practice", "Hands-on exercises and practice problems.")
            ], "#6366f1", "#38bdf8"),
            ("Pointers to Review", "pointers", [
                ("Key Formula", "List of formulas you should memorize."),
                ("Important Concepts", "Concepts you must understand."),
                ("Sample Questions", "Example questions for practice.")
            ], "#f43f5e", "#f87171"),
            ("Assignments", "assignments", [
                ("Assignment 1", "Solve exercises on page 34-35."),
                ("Assignment 2", "Group activity about measurements."),
                ("Assignment 3", "Create a math puzzle.")
            ], "#22c55e", "#a3e635")
        ]

        for title_text, category, items, color_start, color_end in section_data:
            section_widget = QWidget()
            section_layout = QVBoxLayout(section_widget)
            section_layout.setSpacing(18)

            for item_title, item_content in items:
                section_frame = QFrame()
                section_frame.setStyleSheet(f"""
                    QFrame {{
                        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {color_start}, stop:1 {color_end});
                        border-radius: 18px;
                        padding: 14px 16px;
                    }}
                """)
                item_layout = QVBoxLayout(section_frame)
                item_layout.setSpacing(8)

                item_label = QLabel(f"\u2022 <b>{item_title}:</b> {item_content}")
                item_label.setFont(QFont("Segoe UI", 14))
                item_label.setStyleSheet("color: white;")
                item_label.setWordWrap(True)
                item_layout.addWidget(item_label)

                if category == "modules":
                    ask_ai_btn = QPushButton("Ask AI")
                    ask_ai_btn.setVisible(False)
                    ask_ai_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                    ask_ai_btn.setFixedSize(90, 28)
                    ask_ai_btn.setStyleSheet("background-color: #fff59d; font-size: 12px; font-weight: 600; border-radius: 6px; color: #444;")
                    item_layout.addWidget(ask_ai_btn, alignment=Qt.AlignmentFlag.AlignRight)

                    def maybe_show_ai_btn():
                        if item_label.hasSelectedText():
                            ask_ai_btn.setVisible(True)
                        else:
                            ask_ai_btn.setVisible(False)

                    def ask_ai_action():
                        selected_text = item_label.selectedText()
                        if selected_text:
                            choice, ok = QInputDialog.getItem(
                                self, "Ask AI", f"What would you like to do with:\n“{selected_text}”",
                                ["Explain", "Edit"], editable=False
                            )
                            if ok:
                                try:
                                    prompt = f"{choice} the following text:\n\n{selected_text}"
                                    msg_wait = QMessageBox(self)
                                    msg_wait.setWindowTitle("AI Response")
                                    msg_wait.setText("Please wait while AI is processing...")
                                    msg_wait.setStandardButtons(QMessageBox.StandardButton.NoButton)
                                    msg_wait.show()

                                    ai_output = get_ai_response(prompt)

                                    msg_wait.close()
                                    QMessageBox.information(self, f"AI {choice}", ai_output)
                                except Exception as e:
                                    QMessageBox.warning(self, "AI Error", f"Something went wrong:\n{e}")

                    item_label.mouseReleaseEvent = lambda event: (maybe_show_ai_btn(), QLabel.mouseReleaseEvent(item_label, event))
                    ask_ai_btn.clicked.connect(ask_ai_action)

                notes_edit = QTextEdit()
                notes_edit.setPlaceholderText("Private comment...")
                notes_edit.setFont(QFont("Segoe UI", 13))
                notes_edit.setFixedHeight(90)
                note_key = f"{title_text}::{item_title}"
                notes_edit.setText(SAVED_NOTES.get(note_key, ""))

                def save_note(note_key=note_key, notes_edit=notes_edit):
                    SAVED_NOTES[note_key] = notes_edit.toPlainText()
                    try:
                        with open(NOTES_FILE, "w") as f:
                            json.dump(SAVED_NOTES, f, indent=2)
                    except Exception:
                        pass

                notes_edit.textChanged.connect(save_note)
                item_layout.addWidget(notes_edit)

                if category == "assignments":
                    assign_key = f"{subject_name}::{item_title}"

                    upload_btn = QPushButton("Upload File")
                    upload_btn.setStyleSheet("""
                        QPushButton {
                            background-color: white;
                            color: #3b82f6;
                            padding-left: 10px;
                            padding-right: 10px;
                            font-weight: 600;
                            border: 1.5px solid #3b82f6;
                            border-radius: 8px;
                        }
                        QPushButton:hover {
                            background-color: #e0e7ff;
                        }
                        QPushButton:disabled {
                            color: #a5b4fc;
                            border-color: #a5b4fc;
                        }
                    """)
                    upload_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

                    view_btn = QPushButton("View Your Work")
                    view_btn.setStyleSheet("""
                        QPushButton {
                            background-color: white;
                            color: #10b981;
                            padding-left: 10px;
                            padding-right: 10px;
                            font-weight: 600;
                            border: 1.5px solid #10b981;
                            border-radius: 8px;
                        }
                        QPushButton:hover {
                            background-color: #d1fae5;
                        }
                        QPushButton:disabled {
                            color: #6ee7b7;
                            border-color: #6ee7b7;
                        }
                    """)
                    view_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

                    def make_upload_handler(assign_key_local, upload_btn_local, view_btn_local):
                        def upload_file():
                            file_path, _ = QFileDialog.getOpenFileName(self, "Upload Assignment", "", "All Files (*)")
                            if file_path:
                                SUBMITTED_ASSIGNMENTS[assign_key_local] = file_path
                                try:
                                    with open(ASSIGNMENTS_FILE, "w") as f:
                                        json.dump(SUBMITTED_ASSIGNMENTS, f, indent=2)
                                except Exception:
                                    pass
                                upload_btn_local.setText("Uploaded \u2714")
                                upload_btn_local.setEnabled(False)
                                view_btn_local.setEnabled(True)
                        return upload_file

                    def make_view_handler(assign_key_local, upload_btn_local, view_btn_local):
                        def view_or_unsubmit():
                            if assign_key_local in SUBMITTED_ASSIGNMENTS:
                                file_path = SUBMITTED_ASSIGNMENTS[assign_key_local]
                                msg_box = QMessageBox()
                                msg_box.setWindowTitle("Submitted File")
                                file_name = os.path.basename(file_path)
                                msg_box.setText(f"Submitted: {file_name}")
                                msg_box.setInformativeText("What do you want to do?")
                                open_btn = msg_box.addButton("Open File", QMessageBox.ButtonRole.AcceptRole)
                                unsubmit_btn = msg_box.addButton("Unsubmit", QMessageBox.ButtonRole.DestructiveRole)
                                msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                                msg_box.exec()

                                clicked = msg_box.clickedButton()
                                if clicked == unsubmit_btn:
                                    del SUBMITTED_ASSIGNMENTS[assign_key_local]
                                    try:
                                        with open(ASSIGNMENTS_FILE, "w") as f:
                                            json.dump(SUBMITTED_ASSIGNMENTS, f, indent=2)
                                    except Exception:
                                        pass
                                    upload_btn_local.setEnabled(True)
                                    upload_btn_local.setText("Upload File")
                                    view_btn_local.setEnabled(False)
                                elif clicked == open_btn:
                                    QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))
                        return view_or_unsubmit

                    upload_btn.clicked.connect(make_upload_handler(assign_key, upload_btn, view_btn))
                    view_btn.clicked.connect(make_view_handler(assign_key, upload_btn, view_btn))

                    if assign_key in SUBMITTED_ASSIGNMENTS:
                        upload_btn.setText("Uploaded \u2714")
                        upload_btn.setEnabled(False)
                        view_btn.setEnabled(True)
                    else:
                        view_btn.setEnabled(False)

                    item_layout.addWidget(upload_btn)
                    item_layout.addWidget(view_btn)

                section_layout.addWidget(section_frame)

            tab_widget.addTab(section_widget, title_text)

        main_layout.addWidget(tab_widget)

        back_btn = QPushButton("Back to Class")
        back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        back_btn.setStyleSheet("padding: 8px; margin-top: 24px; font-size: 14px; font-weight: 600; max-width: 140px; color: #374151; background-color: #e0e7ff; border-radius: 10px;")
        back_btn.clicked.connect(back_callback)
        main_layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(main_container)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        self.setLayout(layout)


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        name_label = QLabel("Display Name")
        name_label.setFont(QFont("Segoe UI Semibold", 16))
        layout.addWidget(name_label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter your display name")
        self.name_input.setFont(QFont("Segoe UI", 14))
        layout.addWidget(self.name_input)

        pass_label = QLabel("Change Password")
        pass_label.setFont(QFont("Segoe UI Semibold", 16))
        layout.addWidget(pass_label)

        self.old_pass = QLineEdit()
        self.old_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.old_pass.setPlaceholderText("Old Password")
        self.old_pass.setFont(QFont("Segoe UI", 14))
        layout.addWidget(self.old_pass)

        self.new_pass = QLineEdit()
        self.new_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pass.setPlaceholderText("New Password")
        self.new_pass.setFont(QFont("Segoe UI", 14))
        layout.addWidget(self.new_pass)

        self.show_pass = QCheckBox("Show Password")
        self.show_pass.setFont(QFont("Segoe UI", 13))
        self.show_pass.toggled.connect(self.toggle_password_visibility)
        layout.addWidget(self.show_pass)

        update_btn = QPushButton("Update Password")
        update_btn.setFont(QFont("Segoe UI Semibold", 14))
        update_btn.setStyleSheet("background-color: #60a5fa; color: white; padding: 10px; border-radius: 10px;")
        update_btn.clicked.connect(self.update_password)
        layout.addWidget(update_btn)

        notif_label = QLabel("Notifications")
        notif_label.setFont(QFont("Segoe UI Semibold", 16))
        notif_label.setContentsMargins(0, 24, 0, 6)
        layout.addWidget(notif_label)

        self.notif_checkbox = QCheckBox("Enable Email Notifications")
        self.notif_checkbox.setFont(QFont("Segoe UI", 14))
        layout.addWidget(self.notif_checkbox)

        darkmode_label = QLabel("Appearance")
        darkmode_label.setFont(QFont("Segoe UI Semibold", 16))
        darkmode_label.setContentsMargins(0, 24, 0, 6)
        layout.addWidget(darkmode_label)

        self.darkmode_checkbox = QCheckBox("Enable Dark Mode")
        self.darkmode_checkbox.setFont(QFont("Segoe UI", 14))
        layout.addWidget(self.darkmode_checkbox)

        save_btn = QPushButton("Save Settings")
        save_btn.setFont(QFont("Segoe UI Semibold", 14))
        save_btn.setStyleSheet("background-color: #4ade80; color: white; padding: 10px; border-radius: 10px;")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)

        logout_btn = QPushButton("Log Out")
        logout_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        logout_btn.setStyleSheet("background-color: #f87171; color: white; padding: 14px; border-radius: 12px; font-size: 16px; font-weight: 700;")
        logout_btn.clicked.connect(self.logout)
        layout.addWidget(logout_btn)

    def toggle_password_visibility(self):
        mode = QLineEdit.EchoMode.Normal if self.show_pass.isChecked() else QLineEdit.EchoMode.Password
        self.old_pass.setEchoMode(mode)
        self.new_pass.setEchoMode(mode)

    def update_password(self):
        old_pass = self.old_pass.text().strip()
        new_pass = self.new_pass.text().strip()
        if not old_pass or not new_pass:
            QMessageBox.warning(self, "Input Error", "Please enter both old and new passwords.")
            return
        QMessageBox.information(self, "Password Updated", "Your password has been updated successfully.")

    def save_settings(self):
        notif_status = self.notif_checkbox.isChecked()
        dark_status = self.darkmode_checkbox.isChecked()
        display_name = self.name_input.text().strip() or "Student"
        msg = f"Settings saved.\nName: {display_name}\nEmail Notifications: {'Enabled' if notif_status else 'Disabled'}\nDark Mode: {'Enabled' if dark_status else 'Disabled'}"
        QMessageBox.information(self, "Settings", msg)

    def logout(self):
        QMessageBox.information(self, "Logout", "Logging out...")
        QApplication.quit()

# Global helper function for confirmation dialogs
async def ask_confirmation(parent_widget, title, message):
    future = asyncio.Future()
    msg_box = QMessageBox(parent_widget)
    msg_box.setWindowTitle(title)
    msg_box.setText(message)
    msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg_box.buttonClicked.connect(lambda btn: future.set_result(msg_box.standardButton(btn)))
    msg_box.open()
    return await future


class StudentDashboard(QWidget):
    def __init__(self, go_back_callback, student_id):
        super().__init__()
        self.go_back_callback = go_back_callback
        self.current_logged_in_student_id = student_id
        self.setWindowTitle("Student Panel - StudySync")
        self.setMinimumSize(980, 640)
        self.shared_tasks = []
        self.groups_data_from_supabase = {}

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar_widget = QWidget()
        sidebar_widget.setStyleSheet("background-color: #f3f4f6; border-right: 1.5px solid #e5e7eb;")
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(25, 25, 25, 25)
        sidebar_layout.setSpacing(24)

        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setFixedHeight(120)
        logo_label.setText(
            "<div align='center' style='line-height:1.2; font-size: 28px; color: #3b82f6;'>\U0001F393<br><b>StudySync</b></div>")
        logo_label.setTextFormat(Qt.TextFormat.RichText)
        logo_label.setFont(QFont("Segoe UI", 18, QFont.Weight.DemiBold))
        sidebar_layout.addWidget(logo_label)

        self.buttons = {}
        btn_names = ["Dashboard", "Class", "Calendar", "Progress", "Group", "Setting"]
        for name in btn_names:
            btn = QPushButton(name)
            btn.setFont(QFont("Segoe UI", 14))
            btn.setFixedHeight(52)
            btn.setCheckable(True)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    padding-left: 14px;
                    color: #4b5563;
                    text-align: left;
                    font-weight: 600;
                    border-radius: 12px;
                }
                QPushButton:hover {
                    background-color: #e0e7ff;
                    color: #4338ca;
                }
                QPushButton:checked {
                    background-color: #4338ca;
                    color: white;
                }
            """)
            btn.clicked.connect(lambda checked, n=name: self.display_page(n))
            sidebar_layout.addWidget(btn)
            self.buttons[name] = btn

        sidebar_layout.addStretch()

        back_btn = QPushButton("Back")
        back_btn.setFont(QFont("Segoe UI", 14))
        back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        back_btn.setStyleSheet("""
            QPushButton {
                background-color: #f87171;
                color: white;
                padding: 12px;
                border-radius: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
        """)
        back_btn.clicked.connect(go_back_callback)
        sidebar_layout.addWidget(back_btn)

        sidebar_widget.setFixedWidth(220)
        main_layout.addWidget(sidebar_widget)

        self.content_area = QStackedWidget()
        self.pages = {
            "Dashboard": self.create_dashboard_overview(),
            "Class": self.create_class_page(),
            "Calendar": self.create_calendar_page(),
            "Progress": self.create_progress_page(),
            "Group": self.create_group_page_initial(), # Changed to initial view
            "Setting": SettingsPage()
        }
        for page_name, page_widget in self.pages.items():
            # Only add to stacked widget if not already added.
            # This is important for pages that might be added dynamically later.
            if self.content_area.indexOf(page_widget) == -1:
                self.content_area.addWidget(page_widget)

        main_layout.addWidget(self.content_area)

        self.setLayout(main_layout)

        self.display_page("Dashboard")

    async def _get_student_full_name(self, student_pk_id):
        """Fetches the full name of a student given their primary key ID."""
        students, error = await supabase_db_client.select_records( # Changed return value
            "students",
            filters=[("id", "eq", student_pk_id)],
            limit=1
        )
        if error:
            QMessageBox.critical(self, "Database Error", f"Error fetching student name: {error}")
            return str(student_pk_id) # Fallback to ID on error

        if students and 'fullname' in students[0]:
            return students[0]['fullname']
        return str(student_pk_id) # Fallback to ID if name not found or column missing


    # New method to create the initial Group page (list of groups + create group)
    def create_group_page_initial(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        title = QLabel("👥 Group Collaboration Spaces")
        title.setFont(QFont("Segoe UI Semibold", 20))
        title.setStyleSheet("color: #2563eb;")
        layout.addWidget(title)

        # New Group creation input and button
        create_group_layout = QHBoxLayout()
        self.new_group_name_input = QLineEdit()
        self.new_group_name_input.setPlaceholderText("Enter new group name...")
        create_group_layout.addWidget(self.new_group_name_input)
        create_group_btn = QPushButton("➕ Create Group")
        create_group_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        create_group_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                padding: 10px 16px;
                border-radius: 10px;
                font-weight: 600;
                border: none;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:pressed {
                background-color: #1e7e34;
            }
        """)
        create_group_btn.clicked.connect(lambda: asyncio.create_task(self.create_new_group()))
        create_group_layout.addWidget(create_group_btn)
        layout.addLayout(create_group_layout)

        # List of existing groups
        self.group_list = QListWidget()
        self.group_list.setFixedHeight(200) # Give it some height for initial display
        # Connect to a method that handles opening the detail view for the selected group
        self.group_list.itemClicked.connect(lambda item: asyncio.create_task(self.show_group_details_view(item)))
        layout.addWidget(self.group_list)

        layout.addStretch() # Push content to the top

        # Initialize the list of groups
        asyncio.create_task(self.update_group_list())

        return widget

    # Refactored: This will be the actual "Group Details" page widget
    class GroupDetailsWidget(QWidget):
        def __init__(self, parent_dashboard, group_id, group_name, group_creator_id):
            super().__init__()
            self.parent_dashboard = parent_dashboard
            self.group_id = group_id
            self.group_name = group_name
            self.group_creator_id = group_creator_id

            layout = QVBoxLayout(self)
            layout.setContentsMargins(30, 30, 30, 30)
            layout.setSpacing(18)

            # Group Name and Back button
            header_layout = QHBoxLayout()
            header_layout.addWidget(QLabel(f"<h2>{self.group_name}</h2>"))
            header_layout.addStretch()
            back_to_groups_btn = QPushButton("Back to Groups")
            back_to_groups_btn.clicked.connect(self.parent_dashboard.show_group_initial_page)
            back_to_groups_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6c757d;
                    color: white;
                    padding: 8px 12px;
                    border-radius: 8px;
                    font-weight: 600;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #5a6268;
                }
            """)
            header_layout.addWidget(back_to_groups_btn)
            layout.addLayout(header_layout)


            # --- Members Section ---
            members_label = QLabel("👥 Members")
            members_label.setFont(QFont("Segoe UI Semibold", 16))
            layout.addWidget(members_label)

            self.member_list = QListWidget()
            self.member_list.setFixedHeight(120)
            layout.addWidget(self.member_list)

            # Invite Member and Leave Group buttons
            member_actions_layout = QHBoxLayout()
            self.invite_member_input = QLineEdit()
            self.invite_member_input.setPlaceholderText("Enter student ID (e.g., 22-12345)")
            member_actions_layout.addWidget(self.invite_member_input)

            invite_member_btn = QPushButton("➕ Invite Member")
            invite_member_btn.setStyleSheet("""
                QPushButton { background-color: #007bff; color: white; border-radius: 8px; font-weight: 600;}
                QPushButton:hover { background-color: #0056b3; }
            """)
            invite_member_btn.clicked.connect(lambda: asyncio.create_task(self.add_member_to_group()))
            member_actions_layout.addWidget(invite_member_btn)

            leave_group_btn = QPushButton("🚪 Leave Group")
            leave_group_btn.setStyleSheet("""
                QPushButton { background-color: #dc3545; color: white; border-radius: 8px; font-weight: 600;}
                QPushButton:hover { background-color: #c82333; }
            """)
            leave_group_btn.clicked.connect(lambda: asyncio.create_task(self.leave_group()))
            member_actions_layout.addWidget(leave_group_btn)

            # Disable 'Leave Group' button for the group creator
            if self.group_creator_id == self.parent_dashboard.current_logged_in_student_id:
                leave_group_btn.setEnabled(False)
            
            layout.addLayout(member_actions_layout)

            # --- Shared Files Section ---
            files_label = QLabel("📂 Shared Files")
            files_label.setFont(QFont("Segoe UI Semibold", 16))
            layout.addWidget(files_label)

            self.file_list_widget = QListWidget()
            self.file_list_widget.setMinimumHeight(150)
            # Connecting both click and double click for different actions
            self.file_list_widget.itemClicked.connect(self._on_file_list_item_clicked)
            self.file_list_widget.itemDoubleClicked.connect(lambda item: asyncio.create_task(self.view_group_file(item)))
            layout.addWidget(self.file_list_widget)

            # Upload and Delete File buttons
            file_actions_layout = QHBoxLayout()
            upload_btn = QPushButton("⬆️ Upload File")
            upload_btn.setStyleSheet("""
                QPushButton { background-color: #28a745; color: white; border-radius: 8px; font-weight: 600;}
                QPushButton:hover { background-color: #218838; }
            """)
            upload_btn.clicked.connect(lambda: asyncio.create_task(self.upload_file_to_group()))
            file_actions_layout.addWidget(upload_btn)

            self.delete_file_btn = QPushButton("🗑️ Delete File")
            self.delete_file_btn.setStyleSheet("""
                QPushButton { background-color: #dc3545; color: white; border-radius: 8px; font-weight: 600;}
                QPushButton:hover { background-color: #c82333; }
            """)
            self.delete_file_btn.clicked.connect(lambda: asyncio.create_task(self.delete_selected_group_file()))
            self.delete_file_btn.setEnabled(False) # Disabled until a file is selected
            file_actions_layout.addWidget(self.delete_file_btn)
            
            layout.addLayout(file_actions_layout)

            # --- Group Chat Section ---
            chat_label = QLabel("💬 Group Chat")
            chat_label.setFont(QFont("Segoe UI Semibold", 16))
            layout.addWidget(chat_label)

            self.chat_box_widget = QListWidget()
            self.chat_box_widget.setMinimumHeight(150)
            layout.addWidget(self.chat_box_widget)

            message_input_layout = QHBoxLayout()
            self.message_input = QLineEdit()
            self.message_input.setPlaceholderText("Type your message here...")
            message_input_layout.addWidget(self.message_input)

            send_btn = QPushButton("Send")
            send_btn.setStyleSheet("""
                QPushButton { background-color: #17a2b8; color: white; border-radius: 8px; font-weight: 600;}
                QPushButton:hover { background-color: #138496; }
            """)
            send_btn.clicked.connect(lambda: asyncio.create_task(self.send_message()))
            message_input_layout.addWidget(send_btn)
            
            layout.addLayout(message_input_layout)

            layout.addStretch() # Push content up

            # Delete Group button at the bottom
            self.delete_group_final_btn = QPushButton("⛔ Delete Group")
            self.delete_group_final_btn.setStyleSheet("""
                QPushButton {
                    background-color: #dc3545;
                    color: white;
                    padding: 12px;
                    border-radius: 10px;
                    font-weight: 700;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #c82333;
                }
            """)
            self.delete_group_final_btn.clicked.connect(lambda: asyncio.create_task(self.delete_group()))
            # Only enable delete group for the creator
            if self.group_creator_id != self.parent_dashboard.current_logged_in_student_id:
                self.delete_group_final_btn.setEnabled(False)
            layout.addWidget(self.delete_group_final_btn)

            # Initialize data
            asyncio.create_task(self.refresh_members_list())
            asyncio.create_task(self.refresh_files_list())
            asyncio.create_task(self.refresh_chat_messages())


        async def refresh_members_list(self):
            self.member_list.clear()
            members_records, error = await supabase_db_client.select_records( # Changed return value
                "group_members",
                filters=[("group_id", "eq", self.group_id)]
            )
            if error:
                QMessageBox.critical(self, "Database Error", f"Error refreshing members: {error}")
                return
            
            for member_rec in members_records:
                member_name = await self.parent_dashboard._get_student_full_name(member_rec['student_id'])
                role = " (Admin)" if member_rec.get('role') == 'admin' else ""
                self.member_list.addItem(f"{member_name}{role}")

        async def add_member_to_group(self):
            student_id_str = self.invite_member_input.text().strip()
            if not student_id_str:
                QMessageBox.warning(self, "Input Error", "Please enter a student ID.")
                return
            if not re.fullmatch(r"\d{2}-\d{5}", student_id_str):
                QMessageBox.warning(self, "Invalid Format", "Student ID must be in format 22-XXXXX.")
                return

            student_lookup, error = await supabase_db_client.select_records("students", filters=[("student_id", "eq", student_id_str)]) # Changed return value
            if error:
                QMessageBox.critical(self, "Database Error", f"Error looking up student: {error}")
                return
            if not student_lookup:
                QMessageBox.warning(self, "Not Found", f"Student with ID '{student_id_str}' not found.")
                return
            target_student_pk_id = student_lookup[0]['id']

            existing_membership, error = await supabase_db_client.select_records( # Changed return value
                "group_members",
                filters=[("group_id", "eq", self.group_id), ("student_id", "eq", target_student_pk_id)]
            )
            if error:
                QMessageBox.critical(self, "Database Error", f"Error checking existing membership: {error}")
                return
            if existing_membership:
                QMessageBox.information(self, "Already Member", f"{student_id_str} is already a member of this group.")
                return

            member_data = {
                "group_id": self.group_id,
                "student_id": target_student_pk_id,
                "role": "member"
            }
            insert_success, error = await supabase_db_client.insert_record("group_members", member_data) # Changed return value
            if error:
                QMessageBox.critical(self, "Error", f"Failed to add student {student_id_str}: {error}")
            else:
                QMessageBox.information(self, "Success", f"Student {student_id_str} added to group.")
                self.invite_member_input.clear()
                await self.refresh_members_list()
                await self.parent_dashboard.update_group_notifications()

        async def leave_group(self):
            # Using the global ask_confirmation function
            confirm_result = await ask_confirmation(self, "Leave Group", f"Are you sure you want to leave '{self.group_name}'?")
            if confirm_result == QMessageBox.StandardButton.Yes:
                delete_success, error = await supabase_db_client.delete_records( # Changed return value
                    "group_members",
                    filters=[("group_id", "eq", self.group_id), ("student_id", "eq", self.parent_dashboard.current_logged_in_student_id)]
                )
                if error:
                    QMessageBox.critical(self, "Error", f"Failed to leave group: {error}")
                else:
                    QMessageBox.information(self, "Left Group", f"You have left '{self.group_name}'.")
                    await self.parent_dashboard.update_group_list()
                    await self.parent_dashboard.update_group_notifications()
                    self.parent_dashboard.show_group_initial_page() # Go back to main group list

        async def refresh_files_list(self):
            self.file_list_widget.clear()
            self.delete_file_btn.setEnabled(False) # Reset button state
            group_files_records, error = await supabase_db_client.select_records( # Changed return value
                "group_files",
                filters=[("group_id", "eq", self.group_id)],
                order_by="uploaded_at.desc"
            )
            if error:
                QMessageBox.critical(self, "Database Error", f"Error refreshing files: {error}")
                return

            for file_rec in group_files_records:
                uploader_name = await self.parent_dashboard._get_student_full_name(file_rec['uploader_id'])
                item_widget = QWidget()
                item_layout = QHBoxLayout(item_widget)
                item_layout.setContentsMargins(0, 0, 0, 0)
                
                # Use a QLabel to display file name, allowing selection
                file_name_label = QLabel(f"{file_rec['file_name']} (by {uploader_name})")
                file_name_label.setProperty("file_id", file_rec['file_id']) # Store file_id on label
                file_name_label.setProperty("supabase_path", file_rec['supabase_path'])
                file_name_label.setProperty("uploader_id", file_rec['uploader_id'])
                item_layout.addWidget(file_name_label)
                item_layout.addStretch()

                list_item = QListWidgetItem(self.file_list_widget)
                list_item.setSizeHint(item_widget.sizeHint())
                list_item.setData(Qt.ItemDataRole.UserRole, file_rec) # Store full record for easy access
                self.file_list_widget.addItem(list_item)
                self.file_list_widget.setItemWidget(list_item, item_widget)
            
            # Reconnect itemClicked only once to the _on_file_list_item_clicked method
            # This is already handled in the __init__ of the GroupDetailsWidget, no need to disconnect/reconnect here.


        def _on_file_list_item_clicked(self, item):
            # Enable delete button when an item is selected
            if item:
                self.delete_file_btn.setEnabled(True)
            else:
                self.delete_file_btn.setEnabled(False)

        async def view_group_file(self, item):
            # Retrieve the full file record stored in the item's UserRole
            file_rec = item.data(Qt.ItemDataRole.UserRole)
            if not file_rec:
                QMessageBox.warning(self, "Error", "Could not retrieve file details for opening.")
                return

            public_url = supabase_storage.get_file_public_url(file_rec['supabase_path'])

            confirm_result = await ask_confirmation(
                self,
                "Open File",
                f"This will open '{file_rec['file_name']}' in your default browser. Continue?"
            )
            if confirm_result == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(public_url))
                QMessageBox.information(self, "Opened", f"Opened '{file_rec['file_name']}' in browser.")


        async def upload_file_to_group(self):
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File to Upload", "", "All Files (*)")
            if file_path:
                file_name = os.path.basename(file_path)
                supabase_storage_path = f"group_files/{self.group_id}/{file_name}"

                progress_dialog = QProgressDialog("Uploading file...", None, 0, 0, self)
                progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
                progress_dialog.setWindowTitle("Uploading")
                progress_dialog.setCancelButton(None)
                progress_dialog.show()

                success, message = await supabase_storage.upload_file(file_path, supabase_storage_path) # Changed return value
                progress_dialog.close()

                if not success:
                    QMessageBox.critical(self, "Upload Failed", f"Failed to upload '{file_name}':\n{message}")
                    return

                file_metadata = {
                    "group_id": self.group_id,
                    "uploader_id": self.parent_dashboard.current_logged_in_student_id,
                    "file_name": file_name,
                    "supabase_path": supabase_storage_path
                }
                inserted_file_record, error = await supabase_db_client.insert_record("group_files", file_metadata) # Changed return value
                if error:
                    QMessageBox.critical(self, "Database Error", f"Failed to record file metadata for '{file_name}': {error}")
                    await supabase_storage.delete_file(supabase_storage_path) # Attempt to clean up uploaded file
                else:
                    QMessageBox.information(self, "Upload Success", f"File '{file_name}' uploaded and recorded successfully.")
                    await self.refresh_files_list()
                    await self.parent_dashboard.update_group_notifications()
                

        async def delete_selected_group_file(self):
            selected_items = self.file_list_widget.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "No Selection", "Please select a file to delete.")
                return

            selected_file_rec = selected_items[0].data(Qt.ItemDataRole.UserRole)
            file_id = selected_file_rec['file_id']
            supabase_path = selected_file_rec['supabase_path']
            uploader_id = selected_file_rec['uploader_id']
            file_name = selected_file_rec['file_name']

            # Check permission: Uploader or Group Creator
            if not (uploader_id == self.parent_dashboard.current_logged_in_student_id or self.group_creator_id == self.parent_dashboard.current_logged_in_student_id):
                QMessageBox.warning(self, "Permission Denied", "Only the uploader or group creator can delete this file.")
                return

            # Using the global ask_confirmation function
            confirm_result = await ask_confirmation(self, "Delete File", f"Are you sure you want to delete '{file_name}'? This action cannot be undone.")
            if confirm_result == QMessageBox.StandardButton.Yes:
                # 1. Delete from Supabase Storage
                delete_storage_success, storage_message = await supabase_storage.delete_file(supabase_path) # Changed return value
                if not delete_storage_success:
                    QMessageBox.critical(self, "Delete Failed", f"Failed to delete file from storage: {storage_message}")
                    return

                # 2. Delete from Supabase Database (group_files table)
                delete_db_success, error = await supabase_db_client.delete_records("group_files", filters=[("file_id", "eq", file_id)]) # Changed return value
                if error:
                    QMessageBox.critical(self, "Delete Failed", f"Failed to delete file record from database: {error}")
                else:
                    QMessageBox.information(self, "Success", f"File '{file_name}' deleted successfully.")
                    await self.refresh_files_list()
                    await self.parent_dashboard.update_group_notifications()


        async def refresh_chat_messages(self):
            self.chat_box_widget.clear()
            group_chats_records, error = await supabase_db_client.select_records( # Changed return value
                "group_chats",
                filters=[("group_id", "eq", self.group_id)],
                order_by="timestamp.asc"
            )
            if error:
                QMessageBox.critical(self, "Database Error", f"Error refreshing chat messages: {error}")
                return

            for chat_rec in group_chats_records:
                sender_name = await self.parent_dashboard._get_student_full_name(chat_rec['sender_id'])
                self.chat_box_widget.addItem(f"{sender_name}: {chat_rec['message']}")
            self.chat_box_widget.scrollToBottom()

        async def send_message(self):
            msg = self.message_input.text().strip()
            if msg:
                chat_data = {
                    "group_id": self.group_id,
                    "sender_id": self.parent_dashboard.current_logged_in_student_id,
                    "message": msg
                }
                new_chat_record, error = await supabase_db_client.insert_record("group_chats", chat_data) # Changed return value
                if error:
                    QMessageBox.critical(self, "Chat Error", f"Failed to send message: {error}")
                else:
                    self.message_input.clear()
                    await self.refresh_chat_messages()
                    await self.parent_dashboard.update_group_notifications()

        async def delete_group(self):
            # Using the global ask_confirmation function
            confirm_result = await ask_confirmation(
                self,
                "Delete Group",
                f"Are you sure you want to delete '{self.group_name}'? This will delete all associated chats and file records. This cannot be undone."
            )
            if confirm_result == QMessageBox.StandardButton.Yes:
                if self.group_creator_id != self.parent_dashboard.current_logged_in_student_id:
                    QMessageBox.warning(self, "Permission Denied", "Only the group creator can delete the group.")
                    return

                # Delete all files in the bucket for this group first
                files_to_delete, error = await supabase_db_client.select_records("group_files", filters=[("group_id", "eq", self.group_id)]) # Changed return value
                if error:
                    QMessageBox.critical(self, "Database Error", f"Error fetching files for deletion: {error}")
                    return

                for file_rec in files_to_delete:
                    _, error = await supabase_storage.delete_file(file_rec['supabase_path']) # Changed return value
                    if error:
                        QMessageBox.warning(self, "File Deletion Warning", f"Could not delete file {file_rec['file_name']} from storage: {error}")

                # Delete group_chats records
                _, error = await supabase_db_client.delete_records("group_chats", filters=[("group_id", "eq", self.group_id)]) # Changed return value
                if error:
                    QMessageBox.warning(self, "Database Warning", f"Could not delete chat records for group: {error}")

                # Delete group_members records
                _, error = await supabase_db_client.delete_records("group_members", filters=[("group_id", "eq", self.group_id)]) # Changed return value
                if error:
                    QMessageBox.warning(self, "Database Warning", f"Could not delete member records for group: {error}")

                # Finally, delete the group record itself
                delete_success, error = await supabase_db_client.delete_records("groups", filters=[("group_id", "eq", self.group_id)]) # Changed return value

                if error:
                    QMessageBox.critical(self, "Error", f"Failed to delete group '{self.group_name}': {error}")
                else:
                    QMessageBox.information(self, "Deleted", f"Group '{self.group_name}' has been deleted, along with its chats and file records.")
                    await self.parent_dashboard.update_group_list()
                    await self.parent_dashboard.update_group_notifications()
                    self.parent_dashboard.show_group_initial_page() # Go back to main group list

    # New method to show the group details page
    async def show_group_details_view(self, item):
        group_id = item.data(Qt.ItemDataRole.UserRole)
        group_name = item.text() # Get group name from list item
        
        # Fetch full group data to get creator_id
        group_records, error = await supabase_db_client.select_records( # Changed return value
            "groups",
            filters=[("group_id", "eq", group_id)],
            limit=1
        )
        if error:
            QMessageBox.warning(self, "Error", f"Could not retrieve group details: {error}")
            return
        if not group_records:
            QMessageBox.warning(self, "Error", "Could not retrieve group details.")
            return
        group_creator_id = group_records[0].get('creator_id')

        # Create the group details widget
        group_details_widget = self.GroupDetailsWidget(self, group_id, group_name, group_creator_id)
        
        # Add and display the group details widget in the stacked widget
        # Ensure it's added only once if not already present
        if self.content_area.indexOf(group_details_widget) == -1:
            self.content_area.addWidget(group_details_widget)
        self.content_area.setCurrentWidget(group_details_widget)

        # Ensure no sidebar button is checked when a detail page is shown
        for btn in self.buttons.values():
            btn.setChecked(False)


    def show_group_initial_page(self):
        # Simply instruct display_page to show the "Group" page, which is the initial list view
        self.display_page("Group")


    async def open_group_from_notification(self, item):
        # This now directly calls the show_group_details_view to ensure the correct page is displayed
        await self.show_group_details_view(item)


    async def create_new_group(self):
        group_name = self.new_group_name_input.text().strip()
        if not group_name:
            QMessageBox.warning(self, "Input Error", "Group name cannot be empty.")
            return

        existing_groups, error = await supabase_db_client.select_records("groups", filters=[("group_name", "eq", group_name)]) # Changed return value
        if error:
            QMessageBox.critical(self, "Database Error", f"Error checking for existing groups: {error}")
            return
        if existing_groups:
            QMessageBox.warning(self, "Group Exists", f"A group named '{group_name}' already exists. Please choose a different name.")
            return

        group_data = {
            "group_name": group_name,
            "creator_id": self.current_logged_in_student_id
        }
        new_group_record, error = await supabase_db_client.insert_record("groups", group_data) # Changed return value

        if error:
            QMessageBox.critical(self, "Error", f"Failed to create group '{group_name}': {error}")
            return

        group_id_from_record = None
        if new_group_record and new_group_record.get('id'):
            group_id_from_record = new_group_record['id']
        elif not new_group_record or not new_group_record.get('id'):
            # Fallback if insert_record doesn't return ID directly (e.g., Supabase 201 No Content)
            fetched_group, fetch_error = await supabase_db_client.select_records( # Changed return value
                "groups",
                filters=[("group_name", "eq", group_name), ("creator_id", "eq", self.current_logged_in_student_id)],
                order_by="created_at.desc",
                limit=1
            )
            if fetch_error:
                QMessageBox.critical(self, "Database Error", f"Error fetching newly created group: {fetch_error}")
                return
            if fetched_group:
                group_id_from_record = fetched_group[0].get('group_id') or fetched_group[0].get('id') 

        if group_id_from_record:
            member_data = {
                "group_id": group_id_from_record,
                "student_id": self.current_logged_in_student_id,
                "role": "admin"
            }
            _, member_insert_error = await supabase_db_client.insert_record("group_members", member_data) # Changed return value
            if member_insert_error:
                QMessageBox.critical(self, "Error", f"Failed to add creator as member to group: {member_insert_error}")
                # Potentially delete the group here if member insertion fails
            else:
                QMessageBox.information(self, "Success", f"Group '{group_name}' created successfully!")
                self.new_group_name_input.clear() # Clear the input field
                await self.update_group_list()
                await self.update_group_notifications()
        else:
            QMessageBox.critical(self, "Error", "Failed to retrieve group ID after creation.")


    async def update_group_list(self):
        self.group_list.clear()
        all_groups, error = await supabase_db_client.select_records("groups", order_by="group_name.asc") # Changed return value
        if error:
            QMessageBox.critical(self, "Database Error", f"Error updating group list: {error}")
            return
        
        self.groups_data_from_supabase = {
            group.get('group_id'): group
            for group in all_groups if group.get('group_id') is not None
        }

        for group in all_groups:
            group_pk_id = group.get('group_id')
            if group_pk_id is not None:
                item = QListWidgetItem(group["group_name"])
                item.setData(Qt.ItemDataRole.UserRole, group_pk_id)
                self.group_list.addItem(item)


    def display_page(self, page_name):
        # Uncheck all buttons first to reset state
        for name, btn in self.buttons.items():
            btn.setChecked(False)

        # Set the current button as checked if it exists in our tracked buttons
        if page_name in self.buttons:
            self.buttons[page_name].setChecked(True)

        target_widget = self.pages.get(page_name)
        if target_widget:
            # Ensure the target widget is currently in the stacked widget
            # and set it as the current widget.
            # This is important if a page was temporarily removed or added dynamically.
            if self.content_area.indexOf(target_widget) == -1:
                self.content_area.addWidget(target_widget) # Add if not already present
            self.content_area.setCurrentWidget(target_widget)
        else:
            # This 'else' block will catch attempts to display pages not pre-registered in self.pages.
            # Dynamic pages like GroupDetailsWidget are handled by specific methods (e.g., show_group_details_view)
            # that directly add them to the stacked widget and set them as current.
            print(f"Warning: Attempted to display unknown or dynamically handled page: {page_name}")
            # Optionally, you could set a default page here or raise an error.


    def create_dashboard_overview(self):
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(28)

        left_layout = QVBoxLayout()
        left_layout.setSpacing(20)

        calendar_label = QLabel("\U0001F4C5 Calendar Preview")
        calendar_label.setFont(QFont("Segoe UI Semibold", 16))
        calendar_label.setStyleSheet("color: #1e40af;")
        left_layout.addWidget(calendar_label)

        calendar = QCalendarWidget()
        calendar.setGridVisible(True)
        calendar.setFixedHeight(240)
        calendar.setFont(QFont("Segoe UI", 13))
        calendar.setStyleSheet("""
            QCalendarWidget QWidget { font-size: 14px; }
            QCalendarWidget QToolButton { height:30px; font-weight: 600; color: #2563eb; }
            QCalendarWidget QAbstractItemView:enabled { font-weight: 600; }
            QCalendarWidget QAbstractItemView:enabled:selected { background-color: #3b82f6; color: white; border-radius: 6px; }
        """)
        left_layout.addWidget(calendar)

        graph_label = QLabel("\n\U0001F4C8 Weekly Score Snapshot")
        graph_label.setFont(QFont("Segoe UI Semibold", 16))
        graph_label.setStyleSheet("color: #1e40af;")
        left_layout.addWidget(graph_label)

        fig = Figure(figsize=(6, 3), dpi=120)
        graph_canvas = FigureCanvas(fig)
        graph_canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        graph_canvas.setMinimumHeight(220)
        graph_canvas.setMinimumWidth(740)
        left_layout.addWidget(graph_canvas)

        ax = fig.add_subplot(111)

        key = "This Week"
        subjects = [item[0] for item in progress_data[key]]
        scores = [int(item[1].split(": ")[1].split("/")[0]) if "Graded" in item[1] else 0 for item in
                  progress_data[key]]

        ax.plot(subjects, scores, marker='o', color="#2563eb", linewidth=2)
        ax.fill_between(subjects, scores, color="#93c5fd", alpha=0.3)
        ax.set_ylim(0, 100)
        ax.set_ylabel("Score", fontsize=10, color="#1e40af")
        ax.set_title(f"{key} Scores", fontsize=12, color="#1e40af", weight='bold')
        ax.tick_params(axis='x', labelsize=5.5, rotation=0, colors="#4b5563")
        ax.tick_params(axis='y', labelsize=7, colors="#4b5563")
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#60a5fa')
        ax.spines['bottom'].set_color('#60a5fa')

        ax.grid(True, linestyle='--', alpha=0.25)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(18)

        task_label = QLabel("\ud83d\udccc Today's Tasks")
        task_label.setFont(QFont("Segoe UI Semibold", 16))
        task_label.setStyleSheet("color: #2563eb;")
        right_layout.addWidget(task_label)

        task_list = QListWidget()
        self.task_list_widget = task_list

        task_list.setStyleSheet("""
            QListWidget { font-size: 15px; border-radius: 10px; padding: 8px; }
            QListWidget::item { padding: 8px 12px; }
            QListWidget::item:selected { background-color: #bfdbfe; color: #1e40af; }
        """)
        task_list.addItems(["Math Quiz - 10:00 AM", "Science Lab - 2:00 PM"])
        right_layout.addWidget(task_list)

        upcoming_label = QLabel("\u23f3 Upcoming Activities")
        upcoming_label.setFont(QFont("Segoe UI Semibold", 16))
        upcoming_label.setStyleSheet("color: #2563eb; margin-top: 12px;")
        right_layout.addWidget(upcoming_label)

        upcoming_list = QListWidget()
        upcoming_list.setStyleSheet(task_list.styleSheet())
        upcoming_list.addItems(["Essay Due - June 20", "History Exam - June 22"])
        right_layout.addWidget(upcoming_list)

        group_label = QLabel("👥 Group Updates")
        group_label.setFont(QFont("Segoe UI Semibold", 16))
        group_label.setStyleSheet("color: #2563eb; margin-top: 12px;")
        right_layout.addWidget(group_label)

        self.group_updates_list = QListWidget()
        self.group_updates_list.setStyleSheet(task_list.styleSheet())
        right_layout.addWidget(self.group_updates_list)

        notif_label = QLabel("\ud83d\udce2 Teacher Posts & Announcements")
        notif_label.setFont(QFont("Segoe UI Semibold", 16))
        notif_label.setStyleSheet("color: #2563eb; margin-top: 12px;")
        right_layout.addWidget(notif_label)

        notif_list = QListWidget()
        notif_list.setStyleSheet(task_list.styleSheet())
        notif_list.addItems(["New Announcement: Review for Final Exam", "Reminder: Submit Science Project"])
        right_layout.addWidget(notif_list)

        asyncio.create_task(self.update_group_notifications())

        main_layout.addLayout(left_layout, 3)
        main_layout.addLayout(right_layout, 2)

        return widget

    def update_dashboard_tasks(self):
        self.task_list_widget.clear()
        for task in self.shared_tasks:
            status = "✓ " if task["completed"] else "✗ "
            due_date = task.get("due_date")
            due_str = due_date.toString("yyyy-MM-dd") if isinstance(due_date, QDate) else "No date"
            item = f"{status}{task['title']} – Due: {due_str}"
            self.task_list_widget.addItem(item)

    async def update_group_notifications(self):
        self.group_updates_list.clear()

        all_groups, error = await supabase_db_client.select_records("groups", order_by="created_at.desc") # Changed return value
        if error:
            QMessageBox.critical(self, "Database Error", f"Error updating group notifications: {error}")
            return

        for group in all_groups:
            group_id = group.get('group_id') # Safely get the ID using 'group_id' from schema
            if group_id is None:
                continue # Skip if no valid ID found

            group_name = group['group_name']

            latest_chat, chat_error = await supabase_db_client.select_records( # Changed return value
                "group_chats",
                filters=[("group_id", "eq", group_id)],
                order_by="timestamp.desc",
                limit=1
            )
            if chat_error:
                print(f"Warning: Error fetching chat for group {group_name}: {chat_error}") # Log but don't block UI
            chat_msg = latest_chat[0] if latest_chat else None

            latest_file, file_error = await supabase_db_client.select_records( # Changed return value
                "group_files",
                filters=[("group_id", "eq", group_id)],
                order_by="uploaded_at.desc",
                limit=1
            )
            if file_error:
                print(f"Warning: Error fetching file for group {group_name}: {file_error}") # Log but don't block UI
            file_rec = latest_file[0] if latest_file else None

            item_text = f"[{group_name}] No recent activity"
            if chat_msg and file_rec:
                chat_time = datetime.fromisoformat(chat_msg['timestamp'].replace('Z', '+00:00'))
                file_time = datetime.fromisoformat(file_rec['uploaded_at'].replace('Z', '+00:00'))
                if chat_time > file_time:
                    sender_name = await self._get_student_full_name(chat_msg['sender_id'])
                    item_text = f"[{group_name}] 💬 {sender_name}: {chat_msg['message']}" # FIX: Changed chat_rec to chat_msg
                else:
                    uploader_name = await self._get_student_full_name(file_rec['uploader_id'])
                    item_text = f"[{group_name}] 📎 File: {file_rec['file_name']} (by {uploader_name})"
            elif chat_msg:
                sender_name = await self._get_student_full_name(chat_msg['sender_id'])
                item_text = f"[{group_name}] 💬 {sender_name}: {chat_msg['message']}" # FIX: Changed chat_rec to chat_msg
            elif file_rec:
                uploader_name = await self._get_student_full_name(file_rec['uploader_id'])
                item_text = f"[{group_name}] 📎 File: {file_rec['file_name']} (by {uploader_name})"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, group_id)
            self.group_updates_list.addItem(item)

        try:
            self.group_updates_list.itemDoubleClicked.disconnect()
        except TypeError:
            pass
        self.group_updates_list.itemDoubleClicked.connect(lambda item: asyncio.create_task(self.open_group_from_notification(item)))


    def create_class_page(self):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(24)
        layout.setContentsMargins(28, 28, 28, 28)

        subjects = [
            ("Mathematics", "\ud83d\udcd0", "#fce7f3"),
            ("Science", "\ud83d\udd2c", "#dbeafe"),
            ("English", "\ud83d\udcda", "#fee2e2"),
            ("History", "\ud83c\udff0", "#e0f2fe"),
            ("Geography", "\ud83d\uddfa\ufe0f", "#dcfce7"),
            ("Computer Science", "\ud83d\udcbb", "#ede9fe"),
            ("Art", "\ud83c\udfa8", "#fef9c3")
        ]

        elegant_font_family = "Georgia"

        for subject, icon, color in subjects:
            box = QPushButton(f"{icon}  {subject}")
            box.setFixedHeight(90)
            box.setFont(QFont(elegant_font_family, 20, QFont.Weight.DemiBold))
            box.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color};
                    border: none;
                    border-radius: 20px;
                    padding: 18px;
                    color: #111827;
                    font-weight: 600;
                    letter-spacing: 0.8px;
                    text-align: left;
                    font-size: 22px;
                }}
                QPushButton:hover {{
                    background-color: #dbeafe;
                    color: #1e3a8a;
                }}
                QPushButton:pressed {{
                    background-color: {color};
                    color: #111827;
                }}
            """)
            box.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            box.clicked.connect(lambda _, s=subject: self.show_subject_detail(s))
            layout.addWidget(box)

        layout.addStretch()
        scroll_area.setWidget(container)
        return scroll_area

    def show_subject_detail(self, subject_name):
        from PyQt6.QtCore import QDate
        detail_page = self.create_subject_detail_page(subject_name)
        self.pages["SubjectDetail"] = detail_page
        self.content_area.addWidget(detail_page)
        self.content_area.setCurrentWidget(detail_page)
        for btn in self.buttons.values():
            btn.setChecked(False)

    def create_subject_detail_page(self, subject_name):
        from PyQt6.QtCore import QDate
        return SubjectDetailPage(subject_name, self.back_to_class)

    def back_to_class(self):
        self.display_page("Class")

    def create_calendar_page(self):
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("\U0001F4C5 Calendar & Task Schedule")
        title.setFont(QFont("Segoe UI Semibold", 20))
        title.setStyleSheet("color: #2563eb;")
        main_layout.addWidget(title)

        split_layout = QHBoxLayout()
        split_layout.setSpacing(32)

        calendar = QCalendarWidget()
        calendar.setStyleSheet("""
            QCalendarWidget QWidget {
                font-size: 13px;
            }
            QCalendarWidget QAbstractItemView {
                padding: 8px;
                selection-background-color: #2563eb;
                selection-color: white;
                gridline-color: #d1d5db;
            }
            QCalendarWidget QToolButton {
                font-size: 14px;
                font-weight: 600;
                color: #1e40af;
            }
            QCalendarWidget QHeaderView::section {
                background-color: #f3f4f6;
                font-weight: bold;
                color: #111827;
            }
        """)

        calendar.setSelectedDate(QDate.currentDate())
        calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.ISOWeekNumbers)

        calendar.setGridVisible(True)
        calendar.setFont(QFont("Segoe UI", 14))
        calendar.setFixedWidth(370)
        calendar.setStyleSheet("""
            QCalendarWidget QWidget { font-size: 14px; }
            QCalendarWidget QToolButton { height:34px; font-weight: 600; color: #2563eb; }
            QCalendarWidget QAbstractItemView:enabled:selected {
                background-color: #3b82f6;
                color: white;
                border-radius: 8px;
            }
        """)
        split_layout.addWidget(calendar)

        right_box = QVBoxLayout()
        right_box.setSpacing(10)
        self.todo_widget = ToDoWidget(self.shared_tasks, self.update_dashboard_tasks)
        right_box.addWidget(self.todo_widget)

        split_layout.addLayout(right_box)
        main_layout.addLayout(split_layout)

        upcoming_label = QLabel("Incoming Activities")
        upcoming_label.setFont(QFont("Segoe UI Semibold", 18))
        upcoming_label.setStyleSheet("color: #2563eb; margin-top: 18px;")
        main_layout.addWidget(upcoming_label)

        self.upcoming_list = QListWidget()
        self.upcoming_list.setStyleSheet("""
            QListWidget { font-size: 15px; border-radius: 10px; padding: 10px; }
            QListWidget::item { padding: 10px 14px; }
        """)
        main_layout.addWidget(self.upcoming_list)

        self.todo_widget.task_list.addItem("Math Quiz - 10:00 AM")
        self.todo_widget.task_list.addItem("Science Lab - 2:00 PM")
        self.upcoming_list.addItems(["Essay Due - June 20", "History Exam - June 22"])

        self.update_dashboard_tasks()

        return widget

    def create_progress_page(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        title = QLabel("\U0001F4CA Progress Tracker")
        title.setFont(QFont("Segoe UI Semibold", 20))
        title.setStyleSheet("color: #2563eb;")
        layout.addWidget(title)

        progress = {
            "This Week": [
                ("Math Homework", "Graded: 90/100", "green"),
                ("Science Quiz", "Ungraded", "gray"),
                ("English Essay", "Graded: 88/100", "green"),
                ("History Quiz", "Graded: 82/100", "green"),
                ("Biology Lab", "Ungraded", "gray"),
                ("PE Fitness Test", "Graded: 92/100", "green"),
                ("Computer Assignment", "Graded: 85/100", "green")
            ],
            "Last Week": [
                ("Math Project", "Graded: 87/100", "green"),
                ("Science Lab", "Ungraded", "gray"),
                ("English Reading", "Graded: 80/100", "green"),
                ("History Report", "Graded: 78/100", "green"),
                ("Art Sketch", "Ungraded", "gray"),
                ("Geography Quiz", "Graded: 84/100", "green"),
                ("Music Composition", "Graded: 90/100", "green")
            ],
            "Last Month": [
                ("Math Exam", "Graded: 75/100", "green"),
                ("Science Fair", "Graded: 93/100", "green"),
                ("English Portfolio", "Ungraded", "gray"),
                ("History Debate", "Graded: 85/100", "green"),
                ("Computer Lab", "Graded: 80/100", "green"),
                ("Art Exhibit", "Ungraded", "gray"),
                ("Geography Map", "Graded: 86/100", "green")
            ]
        }

        FigureCanvas(Figure()).figure.subplots().tick_params(axis='x', labelsize=5)

        self.dropdown = QComboBox()
        self.dropdown.setFont(QFont("Segoe UI", 14))
        self.dropdown.addItems(progress.keys())
        self.dropdown.setCurrentText("This Week")
        layout.addWidget(self.dropdown)

        self.activity_list = QListWidget()
        self.activity_list.setStyleSheet("""
            QListWidget { font-size: 15px; border-radius: 10px; padding: 10px; }
            QListWidget::item { padding: 10px 14px; }
        """)
        layout.addWidget(self.activity_list)

        graph_title = QLabel("\n\ud83d\udcc8 Performance Trend")
        graph_title.setFont(QFont("Segoe UI Semibold", 18))
        graph_title.setStyleSheet("color: #2563eb;")
        layout.addWidget(graph_title)

        self.canvas = FigureCanvas(Figure(figsize=(6, 2.5), dpi=120))
        layout.addWidget(self.canvas)
        self.ax = self.canvas.figure.add_subplot(111)

        def update_graph(filter_key):
            self.ax.clear()
            subjects = [s[0] for s in progress[filter_key]]
            scores = []
            for item in progress[filter_key]:
                if "Graded" in item[1]:
                    score = int(item[1].split(": ")[1].split("/")[0])
                else:
                    score = 0
                scores.append(score)
            self.ax.plot(subjects, scores, marker='o', linestyle='-', color="#2563eb", linewidth=2)
            self.ax.fill_between(subjects, scores, color="#93c5fd", alpha=0.3)
            self.ax.tick_params(axis='x', labelsize=8, rotation=0, colors='#4b5563')
            self.ax.tick_params(axis='y', labelsize=9, colors='#4b5563')
            self.ax.set_ylim(0, 100)
            self.ax.set_ylabel("Score", fontsize=11, color="#1e40af")
            self.ax.set_title(f"{filter_key} Scores", fontsize=14, color="#1e40af", weight='bold')
            self.ax.spines['top'].set_visible(False)
            self.ax.spines['right'].set_visible(False)
            self.ax.spines['left'].set_color('#60a5fa')
            self.ax.spines['bottom'].set_color('#60a5fa')

            self.ax.grid(True, linestyle='--', alpha=0.25)
            self.canvas.draw()

        def update_activity_list():
            self.activity_list.clear()
            selected = self.dropdown.currentText()
            for subject, status, color in progress[selected]:
                item = QListWidgetItem(f"{subject} - {status}")
                item.setForeground(QColor(color))
                self.activity_list.addItem(item)
            update_graph(selected)

        self.dropdown.currentTextChanged.connect(update_activity_list)
        update_activity_list()

        layout.addStretch()
        return widget


class WelcomeWindow(QWidget):
    def __init__(self, student_no, continue_callback):
        super().__init__()
        self.student_no = student_no
        self.continue_callback = continue_callback
        self.setWindowTitle("Welcome")
        self.setFixedSize(450, 350)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)
        self.setup_ui()
        self.init_animation()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        icon_label = QLabel("\U0001F44B")
        icon_label.setFont(QFont("Segoe UI Emoji", 60))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        welcome_label = QLabel()
        welcome_label.setText(f"""<h1 style="color: qlineargradient(
            spread:pad, x1:0, y1:0, x2:1, y2:0,
            stop:0 #3366ff, stop:1 #6fb1fc); font-weight:bold;">
            Welcome!</h1>""")
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(welcome_label)

        student_label = QLabel(f"Student Number: <b>{self.student_no}</b>")
        student_label.setFont(QFont("Segoe UI", 16))
        student_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        student_label.setStyleSheet("color: #555555;")
        layout.addWidget(student_label)

        note_label = QLabel("You have successfully logged in.\nEnjoy your session!")
        note_label.setFont(QFont("Segoe UI", 13))
        note_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note_label.setStyleSheet("color: #666666;")
        layout.addWidget(note_label)

        self.continue_btn = QPushButton("Continue")
        self.continue_btn.setFont(QFont("Segoe UI", 14))
        self.continue_btn.setFixedHeight(45)
        self.continue_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.continue_btn.setStyleSheet("""
            QPushButton {
                background-color: #3366ff;
                color: white;
                border-radius: 10px;
                padding: 10px 20px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #254eda;
            }
            QPushButton:pressed {
                background-color: #1a3bb8;
            }
        """)
        self.continue_btn.clicked.connect(self.continue_callback)
        layout.addWidget(self.continue_btn)

        layout.addStretch()
        self.setLayout(layout)

    def init_animation(self):
        self.setWindowOpacity(0.0)
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(700)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def showEvent(self, event):
        self.animation.start()
        super().showEvent(event)


class LoginWindow(QWidget):
    def __init__(self, role, on_login_callback, go_back_callback):
        super().__init__()
        self.setWindowTitle(f"{role} Login")
        self.setFixedSize(420, 320)
        self.role = role
        self.on_login_callback = on_login_callback
        self.go_back_callback = go_back_callback
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(18)

        title_label = QLabel("Study <b style='color:#3366ff;'>Sync</b>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setFont(QFont("Segoe UI Semibold", 26))
        title_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title_label)

        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText(f"{self.role} No.")
        self.id_input.setFont(QFont("Segoe UI", 14))
        self.id_input.setFixedHeight(38)
        layout.addWidget(self.id_input)

        self.password_layout = QHBoxLayout()
        self.password_layout.setSpacing(8)
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setFont(QFont("Segoe UI", 14))
        self.password_input.setFixedHeight(38)

        self.toggle_pw_btn = QPushButton("\ud83d\udc41")
        self.toggle_pw_btn.setCheckable(True)
        self.toggle_pw_btn.setFixedSize(40, 40)
        self.toggle_pw_btn.setStyleSheet("font-size: 18px; background-color: transparent; border: none;")
        self.toggle_pw_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.toggle_pw_btn.clicked.connect(self.toggle_password_visibility)

        self.password_layout.addWidget(self.password_input)
        self.password_layout.addWidget(self.toggle_pw_btn)
        layout.addLayout(self.password_layout)

        options_layout = QHBoxLayout()
        self.remember_checkbox = QCheckBox("Remember me?")
        self.remember_checkbox.setFont(QFont("Segoe UI", 13))
        options_layout.addWidget(self.remember_checkbox)

        options_layout.addStretch()

        self.forgot_label = QLabel("<a href='#'>Forgot password?</a>")
        self.forgot_label.setFont(QFont("Segoe UI", 13))
        self.forgot_label.setTextFormat(Qt.TextFormat.RichText)
        self.forgot_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.forgot_label.setOpenExternalLinks(True)
        options_layout.addWidget(self.forgot_label)

        layout.addLayout(options_layout)

        login_btn = QPushButton("Login")
        login_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        login_btn.setFont(QFont("Segoe UI Semibold", 16))
        login_btn.setFixedHeight(40)
        login_btn.setFixedWidth(340)
        login_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #3b82f6;
                        color: white;
                        border-radius: 12px;
                        padding: 10px 0;
                        font-weight: 700;
                    }
                    QPushButton:hover {
                        background-color: #2563eb;
                    }
                    QPushButton:pressed {
                        background-color: #1d4ed8;
                    }
                """)
        login_btn.clicked.connect(lambda: asyncio.create_task(self.handle_login()))
        layout.addWidget(login_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        back_btn = QPushButton("Back")
        back_btn.setFont(QFont("Segoe UI", 14))
        back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        back_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f87171;
                        color: white;
                        border-radius: 12px;
                        padding: 10px 0;
                        font-weight: 700;
                    }
                    QPushButton:hover {
                        background-color: #dc2626;
                    }
                """)
        back_btn.setFixedHeight(40)
        back_btn.setFixedWidth(340)
        back_btn.clicked.connect(self.go_back_callback)
        layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setLayout(layout)

    def toggle_password_visibility(self):
        if self.toggle_pw_btn.isChecked():
            self.password_input.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

    async def handle_login(self):
        student_no = self.id_input.text().strip()
        password = self.password_input.text().strip()

        if self.role == "Student":
            if not re.fullmatch(r"\d{2}-\d{5}", student_no):
                QMessageBox.warning(
                    self, "Invalid Student Number",
                    "Please enter a valid student number (e.g., 22-XXXXX)."
                )
                return

            if not student_no or not password:
                QMessageBox.warning(self, "Input Required", "Please enter both student ID and password.")
                return

            students, error = await supabase_db_client.select_records("students", filters=[("student_id", "eq", student_no)]) # Changed return value
            if error:
                QMessageBox.critical(self, "Login Error", f"Database error during login: {error}")
                return

            student_data = students[0] if students else None

            if student_data and student_data.get("password") == password:
                self.logged_in_student_id = student_data['id']
                self.welcome_window = WelcomeWindow(student_no, self.proceed_to_dashboard)
                self.welcome_window.show()
                self.hide()
            else:
                QMessageBox.warning(self, "Login Failed", "Invalid student ID or password. Please try again.")
        else:
            if student_no and password:
                try:
                    self.logged_in_student_id = int(re.sub(r'\D', '', student_no))
                except ValueError:
                    self.logged_in_student_id = 999999999
                self.welcome_window = WelcomeWindow(student_no, self.proceed_to_dashboard)
                self.welcome_window.show()
                self.hide()
            else:
                QMessageBox.warning(self, "Input Required", "Please enter both ID and password.")


    def proceed_to_dashboard(self):
        self.welcome_window.close()
        self.on_login_callback(self.role, self.logged_in_student_id)
        self.close()


class ProfessorWindow(QWidget):
    def __init__(self, go_back_callback):
        super().__init__()
        self.setWindowTitle("Professor Panel")
        self.setMinimumSize(800, 500)
        layout = QVBoxLayout()
        label = QLabel("Professor Dashboard coming soon...")
        label.setFont(QFont("Segoe UI Semibold", 20))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        back_btn = QPushButton("Back")
        back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        back_btn.setFixedWidth(120)
        back_btn.setStyleSheet("""
            QPushButton {
                background-color: #f87171;
                color: white;
                border-radius: 12px;
                padding: 10px 0;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
        """)
        back_btn.clicked.connect(go_back_callback)
        layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.setLayout(layout)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StudySync")
        self.setFixedSize(900, 540)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.addStretch()

        title = QLabel("Study <b style='color:#3366ff;'>Sync.</b>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI Semibold", 36))
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setContentsMargins(0, 0, 0, 40)
        main_layout.addWidget(title)

        professor_btn = self.create_role_button("Professor", "\U0001F9D1\u200D\U0001F3EB", self.open_professor_login)
        student_btn = self.create_role_button("Student", "\U0001F393", self.open_student_login)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(professor_btn)
        button_layout.addSpacing(60)
        button_layout.addWidget(student_btn)
        button_layout.addStretch()

        main_layout.addLayout(button_layout)
        main_layout.addStretch()

    def create_role_button(self, label, icon_text, callback):
        btn = QPushButton(f"{icon_text}\n{label}")
        btn.setFont(QFont("Segoe UI Semibold", 20))
        btn.setFixedSize(230, 230)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.85);
                border-radius: 30px;
                border: 2px solid transparent;
                padding: 30px;
                color: #374151;
                font-weight: 700;
                letter-spacing: 0.8px;
            }
            QPushButton:hover {
                background-color: rgba(240, 240, 240, 0.95);
                border-color: #3366ff;
                color: #1e40af;
            }
            QPushButton:pressed {
                background-color: #dbeafe;
                border-color: #3b82f6;
            }
        """)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 70))
        shadow.setOffset(4, 4)
        btn.setGraphicsEffect(shadow)
        btn.clicked.connect(callback)
        return btn

    def open_professor_login(self):
        self.login_window = LoginWindow("Professor", self.show_dashboard, self.show_main)
        self.login_window.show()
        self.hide()

    def open_student_login(self):
        self.login_window = LoginWindow("Student", self.show_dashboard, self.show_main)
        self.login_window.show()
        self.hide()

    def show_dashboard(self, role, student_id=None):
        if role == "Professor":
            self.dashboard = ProfessorWindow(self.show_main)
        else:
            self.dashboard = StudentDashboard(self.show_main, student_id)
        self.dashboard.show()
        self.login_window.close()

    def show_main(self):
        self.show()
        if hasattr(self, "login_window"):
            self.login_window.close()
        if hasattr(self, "dashboard"):
            self.dashboard.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow() 
    window.show()
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    with loop:
        loop.run_forever()
