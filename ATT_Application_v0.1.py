import tkinter as tk
from tkinter import messagebox, ttk
import customtkinter as ctk
import serial
import serial.tools.list_ports
import time
import os
import datetime

# Опит за импортиране на matplotlib за графиките на историята
try:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# --- Настройки на CustomTkinter ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# --- Палитра от Матови/Пастелни Цветове ---
BG_SOLID = "#18181a"
MATTE_GREEN = "#3b5e40"
MATTE_GREEN_HOVER = "#2a452e"
MATTE_RED = "#8c3a3a"
MATTE_RED_HOVER = "#692b2b"
MATTE_BLUE = "#3a5c7c"
MATTE_BLUE_HOVER = "#27415e"
MATTE_GRAY = "#3a3a3a"
DEFAULT_BTN_COLOR = "#333333"

# --- Constants ---
PISTON_GROUPS = {
    "Splitter Piston": ["Y2", "Y3"],
    "Select Piston": ["Y5", "Y4"],
    "Shift Piston": ["Y6", "Y7"],
    "Range Piston": ["Y8", "Y9"],
}
OTHER_SOLENOIDS = ["Y1", "Y10"]
SOLENOID_NAMES = ["Y1", "Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9", "Y10"]
TEST_NAMES = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "RL", "RH"]
SENSOR_DISPLAY_CONFIG = [
    ("Splitter Sensor", 1),
    ("Select Sensor", 2),
    ("Shift Sensor", 3),
    ("Range Sensor", 4),
    ("Sensor 5", 5),
    ("Sensor 6", 6)
]
PRESSURE_SENSOR_CONFIG = {"title": "System Pressure", "unit": "bar"}
INDUCTANCE_DISPLAY_CONFIG = [
    ("Splitter Piston", 1, 0, 8.57, 18.57, 92.25, 102.25, 120),
    ("Select Piston", 2, 0, 9.39, 19.39, 83.66, 93.66, 120),
    ("Shift Piston", 3, 0, 7.15, 17.15, 92.08, 102.08, 120),
    ("Range Piston", 4, 0, 9.68, 19.68, 77.46, 87.46, 120)
]
PISTON_SOLENOID_MAP = {
    1: {"OUT": "Y2", "IN": "Y3"},
    2: {"OUT": "Y6", "IN": "Y7"},
    3: {"OUT": "Y8", "IN": "Y9"},
    4: {"OUT": "Y5", "IN": "Y4"},
}
OVERTEMP_WARN_SECONDS = 60
OVERTEMP_CRIT_SECONDS = 120
PISTON_GAUGE_HEIGHT = 50

class SolenoidApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ZF GS3 Solenoid Tester")
        self.root.geometry("1800x850")
        self.root.minsize(1300, 700)
        
        self.root.configure(fg_color=BG_SOLID)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        app_frame = ctk.CTkFrame(root, corner_radius=0, fg_color=BG_SOLID)
        app_frame.pack(fill="both", expand=True)
        
        self.ser = None
        self.state_vars, self.state_labels = {}, {}
        self.sensor_value_vars, self.sensor_value_labels = [], []
        self.sensor_channel_to_widget = {}
        
        # Специфични променливи за новите Features (Ток, Волтаж и Налягане)
        self.pressure_value_var = tk.StringVar(value="--- bar")
        self.voltage_value_var = tk.StringVar(value="--- V")
        self.solenoid_current_vars = {}
        self.solenoid_current_labels = {}
        
        self.full_inductance_vars = self.create_widget_lists(4)
        self.manual_inductance_vars = self.create_widget_lists(4)
        self.auto_inductance_vars = self.create_widget_lists(4)
        self.current_states = ["UNKNOWN"] * len(SOLENOID_NAMES)
        self.auto_sequence_states = ["pending"] * len(TEST_NAMES)
        self.last_auto_step_name = "-"
        
        self.overtemp_labels = {}
        self.solenoid_on_times = {}
        self.solenoid_buttons, self.predefined_buttons, self.individual_piston_buttons = [], [], []
        self.serial_logged = False
        
        self.sidebar_alert_level = 0
        self.sidebar_blink_state = 0
        self.original_sidebar_text = ""
        self.blinker_after_id = None
        
        self.test_statuses = {name: "pending" for name in TEST_NAMES}
        
        # --- Данни и уиджети за графиките на историята ---
        self.history_data = {}  
        self.history_all_widgets = {} 
        
        # --- Параметри за AI автоматичния тест ---
        self.auto_test_running = False
        self.auto_test_counter = 0
        self.auto_test_max_runs = 10
        
        try:
            with open("tester_log.txt", "w", encoding="utf-8") as f: 
                f.write(f"=== TEST SESSION STARTED AT {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception: 
            pass
        
        self.build_sidebar(app_frame)
        self.right_area = ctk.CTkFrame(app_frame, fg_color=BG_SOLID, corner_radius=0)
        self.right_area.pack(side="left", fill="both", expand=True, padx=10, pady=5)
        
        self.build_top_panel(self.right_area)
        self.content_frame = ctk.CTkFrame(self.right_area, fg_color=BG_SOLID, corner_radius=0)
        self.content_frame.pack(fill="both", expand=True, pady=5)
        
        self.create_pages()
        self.populate_pages()
        self.build_info_panel(self.right_area)
        
        self.refresh_ports()
        self.refresh_auto_sequence_list()
        self.reset_all_cards()
        self.poll_serial()
        self.check_overtemp()
        
        self.show_page("manual_solenoids")
        self.update_interlock_states()

    def create_widget_lists(self, count):
        return { 
            "vars": [tk.StringVar(value="---") for _ in range(count)], 
            "labels": [None] * count, 
            "canvases": [None] * count, 
            "channel_map": {} 
        }

    def reset_all_cards(self):
        for i in range(len(self.sensor_value_vars)):
            self.sensor_value_vars[i].set("---")
            self.apply_sensor_style(i, "---")
        self.pressure_value_var.set("--- bar")
        self.apply_pressure_style("---")
        self.voltage_value_var.set("--- V")
        self.apply_voltage_style("---")
        
        for name in SOLENOID_NAMES:
            if name in self.solenoid_current_vars:
                self.solenoid_current_vars[name].set("0.00 A")
            if name in self.solenoid_current_labels:
                self.solenoid_current_labels[name].configure(fg_color="#3a3a3a")
                
        for widget_vars in [self.full_inductance_vars, self.manual_inductance_vars, self.auto_inductance_vars]:
            self.reset_inductance_cards(widget_vars)
        self.test_statuses = {name: "pending" for name in TEST_NAMES}
        self.update_test_button_colors()
        self.history_data.clear()
        for component_name in self.history_all_widgets.keys():
            self.update_history_chart(component_name)

    def build_sidebar(self, parent):
        self.sidebar_frame = ctk.CTkFrame(parent, width=220, corner_radius=0, fg_color=BG_SOLID, border_width=1, border_color="#333333")
        self.sidebar_frame.pack(side="left", fill="y")
        self.sidebar_frame.pack_propagate(False)
        ctk.CTkLabel(self.sidebar_frame, text="ZF GS3", font=("Arial", 22, "bold"), text_color=MATTE_BLUE).pack(pady=20)
        
        self.btn_manual_solenoids = ctk.CTkButton(self.sidebar_frame, text="⚙️ Solenoids MANUAL", height=45, anchor="w", fg_color="transparent", text_color="white", hover_color="#2b2b2b", command=lambda: self.show_page("manual_solenoids"))
        self.btn_manual_solenoids.pack(fill="x", padx=10, pady=5)
        self.original_sidebar_text = self.btn_manual_solenoids.cget("text")
        
        self.btn_auto_tests = ctk.CTkButton(self.sidebar_frame, text="🤖 Auto Tests", height=45, anchor="w", fg_color="transparent", text_color="white", hover_color="#2b2b2b", command=lambda: self.show_page("auto_tests"))
        self.btn_auto_tests.pack(fill="x", padx=10, pady=5)
        
        self.btn_sensors = ctk.CTkButton(self.sidebar_frame, text="📊 Sensors & Position", height=45, anchor="w", fg_color="transparent", text_color="white", hover_color="#2b2b2b", command=lambda: self.show_page("sensors"))
        self.btn_sensors.pack(fill="x", padx=10, pady=5)

        self.btn_history_plot = ctk.CTkButton(self.sidebar_frame, text="📈 History Plot", height=45, anchor="w", fg_color="transparent", text_color="white", hover_color="#2b2b2b", command=lambda: self.show_page("history_plot"))
        self.btn_history_plot.pack(fill="x", padx=10, pady=5)
        
        self.btn_ai_diagnostics = ctk.CTkButton(self.sidebar_frame, text="🧠 AI Diagnostics", height=45, anchor="w", fg_color="transparent", text_color="white", hover_color="#2b2b2b", command=lambda: self.show_page("ai_diagnostics"))
        self.btn_ai_diagnostics.pack(fill="x", padx=10, pady=5)

        self.btn_logs = ctk.CTkButton(self.sidebar_frame, text="📝 Serial Log History", height=45, anchor="w", fg_color="transparent", text_color="white", hover_color="#2b2b2b", command=lambda: self.show_page("logs"))
        self.btn_logs.pack(fill="x", padx=10, pady=5)
        
        # Обединен контейнер за системните показатели в страничното меню
        indicators_container = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        indicators_container.pack(side="bottom", fill="x", pady=20, padx=10)
        
        # Входящо 24V напрежение
        ctk.CTkLabel(indicators_container, text="System Voltage", font=("Arial", 12, "bold"), text_color="#aaaaaa").pack()
        self.voltage_value_label = ctk.CTkLabel(indicators_container, textvariable=self.voltage_value_var, width=180, height=45, fg_color="#333333", text_color="white", corner_radius=8, font=("Arial", 20, "bold"))
        self.voltage_value_label.pack(pady=(2, 12))
        
        # Системно налягане
        ctk.CTkLabel(indicators_container, text="System Pressure", font=("Arial", 12, "bold"), text_color="#aaaaaa").pack()
        self.pressure_value_label = ctk.CTkLabel(indicators_container, textvariable=self.pressure_value_var, width=180, height=45, fg_color="#333333", text_color="white", corner_radius=8, font=("Arial", 20, "bold"))
        self.pressure_value_label.pack(pady=(2, 0))

    def create_pages(self):
        self.page_manual_solenoids = ctk.CTkFrame(self.content_frame, fg_color=BG_SOLID, corner_radius=0)
        self.page_auto_tests = ctk.CTkFrame(self.content_frame, fg_color=BG_SOLID, corner_radius=0)
        self.page_sensors = ctk.CTkFrame(self.content_frame, fg_color=BG_SOLID, corner_radius=0)
        self.page_history_plot = ctk.CTkFrame(self.content_frame, fg_color=BG_SOLID, corner_radius=0)
        self.page_ai_diagnostics = ctk.CTkFrame(self.content_frame, fg_color=BG_SOLID, corner_radius=0)
        self.page_logs = ctk.CTkFrame(self.content_frame, fg_color=BG_SOLID, corner_radius=0)

    def populate_pages(self):
        self.page_manual_solenoids.grid_rowconfigure(0, weight=1)
        self.page_manual_solenoids.grid_columnconfigure(0, weight=0)
        self.page_manual_solenoids.grid_columnconfigure(1, weight=1)
        self.build_solenoid_panel(self.page_manual_solenoids)
        self.build_simple_inductance_panel(self.page_manual_solenoids, self.manual_inductance_vars, "Piston Positions", "nsew")
        
        self.page_auto_tests.grid_rowconfigure(0, weight=1)
        self.page_auto_tests.grid_columnconfigure(0, weight=0)
        self.page_auto_tests.grid_columnconfigure(1, weight=1)
        
        tests_container = ctk.CTkFrame(self.page_auto_tests, fg_color="transparent")
        tests_container.grid(row=0, column=0, sticky="ns", padx=10, pady=10)
        self.build_tests_panel(tests_container)
        self.build_auto_panel(tests_container)
        
        right_column_frame = ctk.CTkFrame(self.page_auto_tests, fg_color="transparent")
        right_column_frame.grid(row=0, column=1, sticky="nsew", padx=(0,10), pady=10)
        right_column_frame.grid_rowconfigure(0, weight=0) 
        right_column_frame.grid_rowconfigure(1, weight=1) 
        right_column_frame.grid_columnconfigure(0, weight=1)
        
        self.build_simple_inductance_panel(right_column_frame, self.auto_inductance_vars, "Current Piston Positions", "new", col=0, row=0)
        self.build_test_results_panel(right_column_frame)
        
        self.page_sensors.rowconfigure(0, weight=1)
        self.page_sensors.grid_columnconfigure(0, weight=1)
        self.page_sensors.grid_columnconfigure(1, weight=1)
        self.build_sensor_panel(self.page_sensors)
        self.build_inductance_panel(self.page_sensors)
        
        self.build_history_plot_page(self.page_history_plot)
        self.build_ai_diagnostics_page(self.page_ai_diagnostics)
        self.build_log_panel(self.page_logs)

    def show_page(self, page_name):
        for page in [self.page_manual_solenoids, self.page_auto_tests, self.page_sensors, self.page_history_plot, self.page_ai_diagnostics, self.page_logs]: 
            page.pack_forget()
        
        buttons = {
            "manual_solenoids": self.btn_manual_solenoids, 
            "auto_tests": self.btn_auto_tests, 
            "sensors": self.btn_sensors, 
            "history_plot": self.btn_history_plot,
            "ai_diagnostics": self.btn_ai_diagnostics,
            "logs": self.btn_logs
        }
        
        is_blinking = self.sidebar_alert_level > 0 and page_name != "manual_solenoids"
        
        for name, btn in buttons.items():
            if name == "manual_solenoids" and is_blinking:
                continue
            btn.configure(fg_color="transparent")
        
        if hasattr(self, 'info_panel'):
            if page_name in ["sensors", "history_plot", "ai_diagnostics"]:
                self.info_panel.pack_forget()
            else:
                self.info_panel.pack(fill="x", padx=10, pady=5)
        
        pages = {
            "manual_solenoids": self.page_manual_solenoids, 
            "auto_tests": self.page_auto_tests, 
            "sensors": self.page_sensors, 
            "history_plot": self.page_history_plot,
            "ai_diagnostics": self.page_ai_diagnostics,
            "logs": self.page_logs
        }
        
        if page_name in pages:
            pages[page_name].pack(fill="both", expand=True)
            if not (page_name == "manual_solenoids" and self.sidebar_alert_level > 0):
                buttons[page_name].configure(fg_color=MATTE_BLUE)
                
            if page_name == "history_plot":
                for component_name in self.history_all_widgets.keys():
                    self.update_history_chart(component_name)

    def update_interlock_states(self):
        is_not_connected = not (self.ser and self.ser.is_open)
        self.port_combo.configure(state="readonly" if is_not_connected else "disabled")
        self.refresh_ports_btn.configure(state="normal" if is_not_connected else "disabled")
        self.connect_btn.configure(state="normal" if is_not_connected else "disabled")
        self.disconnect_btn.configure(state="disabled" if is_not_connected else "normal")
        test_state = "normal" if (self.serial_logged and not is_not_connected) else "disabled"
        for btn_list in [self.solenoid_buttons, self.predefined_buttons, self.individual_piston_buttons]:
            if btn_list:
                for btn in btn_list: 
                    btn.configure(state=test_state)
        if hasattr(self, 'auto_start_btn'): self.auto_start_btn.configure(state=test_state)
        if hasattr(self, 'auto_stop_btn'): self.auto_stop_btn.configure(state=test_state)
        if hasattr(self, 'check_sensors_btn'): self.check_sensors_btn.configure(state=test_state)
        if hasattr(self, 'check_positions_btn'): self.check_positions_btn.configure(state=test_state)
        if hasattr(self, 'auto_test_btn') and self.auto_test_btn: self.auto_test_btn.configure(state=test_state)
        if hasattr(self, 'pdf_report_btn'): self.pdf_report_btn.configure(state="normal" if self.serial_logged else "disabled")
        self.update_test_button_colors()

    def build_top_panel(self, parent):
        top_frame = ctk.CTkFrame(parent, corner_radius=10, fg_color="#18181a", border_width=1, border_color="#333333")
        top_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(top_frame, text="COM Port:", font=("Arial", 11, "bold")).grid(row=0, column=0, padx=15, pady=8, sticky="w")
        self.port_var = tk.StringVar()
        self.port_combo = ctk.CTkComboBox(top_frame, variable=self.port_var, width=150, state="readonly")
        self.port_combo.grid(row=0, column=1, padx=5, pady=8, sticky="w")
        self.refresh_ports_btn = ctk.CTkButton(top_frame, text="Refresh Ports", width=120, command=self.refresh_ports)
        self.refresh_ports_btn.grid(row=0, column=2, padx=5, pady=8)
        self.connect_btn = ctk.CTkButton(top_frame, text="Connect", width=100, fg_color=MATTE_GREEN, hover_color=MATTE_GREEN_HOVER, command=self.connect_serial)
        self.connect_btn.grid(row=0, column=3, padx=5, pady=8)
        self.disconnect_btn = ctk.CTkButton(top_frame, text="Disconnect", width=100, fg_color=MATTE_RED, hover_color=MATTE_RED_HOVER, command=self.disconnect_serial)
        self.disconnect_btn.grid(row=0, column=4, padx=5, pady=8)
        
        self.estop_btn = ctk.CTkButton(top_frame, text="🚨 EMERGENCY STOP", width=180, fg_color="#ff3333", hover_color="#cc0000", text_color="white", font=("Arial", 11, "bold"), command=self.emergency_stop)
        top_frame.grid_columnconfigure(5, weight=1)
        self.estop_btn.grid(row=0, column=5, padx=20, pady=8, sticky="e")

    def emergency_stop(self):
        self.log("🚨🚨🚨 EMERGENCY STOP TRIGGERED! 🚨🚨🚨")
        
        self.auto_test_running = False
        self.auto_test_status_label.configure(text="Status: E-STOPPED")
        self.auto_test_btn.configure(state="normal")
        
        self.auto_sequence_states = ["pending"] * len(TEST_NAMES)
        self.auto_progress["value"] = 0
        self.auto_state_var.set("Auto sequence: E-STOPPED")
        self.auto_current_var.set("Current step: Emergency Stopped")
        self.refresh_auto_sequence_list()
        
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(b"AUTO STOP\n")
                time.sleep(0.05)
                self.ser.write(b"SETOFF ALL\n")
                self.log("PC -> Arduino: EMERGENCY STOP COMMANDS SENT!")
            except Exception as e:
                self.log(f"E-Stop Serial Error: {e}")
        else:
            messagebox.showwarning("E-Stop Warning", "Not connected to Arduino, but local states are reset.")
            
        for name in SOLENOID_NAMES:
            channel = SOLENOID_NAMES.index(name) + 1
            self.set_state(channel, "OFF")
            
            # Нулиране на токовете при авариен стоп
            if name in self.solenoid_current_vars:
                self.solenoid_current_vars[name].set("0.00 A")
            if name in self.solenoid_current_labels:
                self.solenoid_current_labels[name].configure(fg_color="#3a3a3a")
            
        messagebox.showerror("EMERGENCY STOP", "🚨 Аварийно спиране! Всички соленоиди и автоматични тестове са деактивирани веднага!")

    def build_info_panel(self, parent):
        self.info_panel = ctk.CTkFrame(parent, corner_radius=10, fg_color="#18181a", border_width=1, border_color="#333333")
        self.info_panel.pack(fill="x", padx=10, pady=5)
        self.connection_var = tk.StringVar(value="Not connected")
        self.mode_var = tk.StringVar(value="Mode: Unknown")
        self.auto_state_var = tk.StringVar(value="Auto sequence: STOPPED")
        self.auto_current_var = tk.StringVar(value="Current step: -")
        ctk.CTkLabel(self.info_panel, textvariable=self.connection_var, font=("Arial", 11)).grid(row=0, column=0, padx=15, pady=8, sticky="w")
        ctk.CTkLabel(self.info_panel, textvariable=self.mode_var, font=("Arial", 11, "bold")).grid(row=0, column=1, padx=20, pady=8, sticky="w")
        ctk.CTkLabel(self.info_panel, text="Block Serial No:", font=("Arial", 11, "bold")).grid(row=0, column=2, padx=(40, 5), pady=8, sticky="w")
        self.serial_var = tk.StringVar(value="")
        self.serial_entry = ctk.CTkEntry(self.info_panel, textvariable=self.serial_var, width=150, font=("Consolas", 11, "bold"))
        self.serial_entry.grid(row=0, column=3, padx=5, pady=8, sticky="w")
        self.log_serial_btn = ctk.CTkButton(self.info_panel, text="Log Serial", width=100, command=self.log_serial_number)
        self.log_serial_btn.grid(row=0, column=4, padx=5, pady=8, sticky="w")
        self.pdf_report_btn = ctk.CTkButton(self.info_panel, text="PDF Report", width=100, fg_color=MATTE_BLUE, hover_color=MATTE_BLUE_HOVER, command=self.generate_pdf_report)
        self.pdf_report_btn.grid(row=0, column=5, padx=15, pady=8, sticky="w")
        
    def log_serial_number(self):
        serial_no = self.serial_var.get().strip()
        if not serial_no: return messagebox.showwarning("Warning", "Please enter a valid Serial Number first.")
        self.serial_logged = True
        self.log(f"{'='*50}\n>>> TESTING BLOCK SERIAL NUMBER: {serial_no} <<<\n{'='*50}")
        self.reset_all_cards()
        self.update_interlock_states()

    def generate_pdf_report(self):
        if not (serial_no := self.serial_var.get().strip()): return messagebox.showwarning("Warning", "Please enter a Serial Number before generating a report.")
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors
        except ImportError: return messagebox.showerror("Error", "Please install reportlab library first: pip install reportlab")
        filename, story = f"TCU_{serial_no}_report.pdf", []
        doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        primary_color, styles = colors.HexColor('#1565c0'), getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=22, leading=26, textColor=primary_color, spaceAfter=20, fontName='Helvetica-Bold')
        subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#555555'))
        section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=14, textColor=primary_color, spaceBefore=15, spaceAfter=10, fontName='Helvetica-Bold')
        story.append(Paragraph("TRANSMISSION CONTROL UNIT (TCU) DIAGNOSTIC REPORT", title_style))
        story.append(Paragraph(f"<b>Generated by:</b> ZF GS3 Automated Solenoid Tester | <b>Date/Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))
        story.append(Spacer(1, 15))
        story.append(Table([[""]], colWidths=[530], rowHeights=[2], style=TableStyle([('BACKGROUND', (0,0), (-1,-1), primary_color)])))
        story.append(Spacer(1, 15))
        story.append(Paragraph("1. SYSTEM & COMPONENT INFORMATION", section_style))
        
        # Добавено измерваното напрежение в системния протокол
        info_data = [
            [Paragraph(f"<b>TCU Block Serial Number:</b> {serial_no}", styles['Normal']), Paragraph("<b>Test System:</b> ZF GS3 Bench V1.0", styles['Normal'])],
            [Paragraph("<b>Standard / Compatibility:</b> ZF AS-Tronic", styles['Normal']), Paragraph(f"<b>System Voltage:</b> {self.voltage_value_var.get()}", styles['Normal'])],
            [Paragraph(f"<b>Connection Port:</b> {self.port_var.get() or 'N/A'}", styles['Normal']), Paragraph("", styles['Normal'])]
        ]
        t_info = Table(info_data, colWidths=[265, 265])
        t_info.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOTTOMPADDING', (0,0), (-1,-1), 6)]))
        story.append(t_info)
        story.append(Spacer(1, 15))
        story.append(Paragraph("2. DIAGNOSTIC MEASUREMENTS LOG", section_style))
        def get_status(val): return "OK" if "---" not in val else "Not tested"
        meas_data = [["Component tested", "Measured Value", "Status"], *[[f"Sensor {i+1} (Resistive)", v.get(), get_status(v.get())] for i, v in enumerate(self.sensor_value_vars)], *[[f"Piston {i+1} Position (Inductive)", v.get(), get_status(v.get())] for i, v in enumerate(self.full_inductance_vars['vars'])], ["System Pressure", self.pressure_value_var.get(), get_status(self.pressure_value_var.get())]]
        t_meas = Table(meas_data, colWidths=[220, 160, 150])
        t_meas.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), primary_color), ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('ALIGN', (0,0), (-1,-1), 'LEFT'), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('BOTTOMPADDING', (0,0), (-1,0), 6), ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f9f9f9')), ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#e0e0e0')), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        story.append(t_meas)
        story.append(Spacer(1, 20))
        story.append(Paragraph("3. DIAGNOSTIC CONCLUSION", section_style))
        story.append(Paragraph(f"Based on the quantitative and physical parameters registered during the diagnostic sequence, the tested TCU Block S/N {serial_no} has been evaluated.", styles['Normal']))
        story.append(Spacer(1, 35))
        sig_data = [[Paragraph("<b>Technician Signature:</b> .......................................", styles['Normal']), Paragraph("<b>Workshop Stamp:</b>", styles['Normal'])]]
        t_sig = Table(sig_data, colWidths=[300, 230])
        t_sig.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
        story.append(t_sig)
        doc.build(story)
        messagebox.showinfo("Success", f"Professional PDF Report generated and saved locally as TCU_{serial_no}_report.pdf")

    # --- РАЗШИРЕН ПАНЕЛ ЗА СОЛЕНОИДИ С КОЛОНА "CURRENT" (ТОК) ---
    def build_solenoid_panel(self, parent):
        solenoid_frame = ctk.CTkFrame(parent, corner_radius=10)
        solenoid_frame.grid(row=0, column=0, sticky="nsw", padx=10, pady=10)
        
        # Обновена структура на хедърите (колона 2 и 3 държат бутоните за контрол)
        headers_config = [
            ("Solenoid", 0, 1),
            ("State", 1, 1),
            ("Control", 2, 2),
            ("Current", 4, 1),
            ("Temperature", 5, 1)
        ]
        for header, col, span in headers_config:
            ctk.CTkLabel(solenoid_frame, text=header, font=("Arial", 11, "bold")).grid(row=0, column=col, columnspan=span, padx=5, pady=5)
        
        current_row = 1
        
        def create_solenoid_row(parent_frame, name, row_idx):
            channel = SOLENOID_NAMES.index(name) + 1
            ctk.CTkLabel(parent_frame, text=f"{name}", anchor="w").grid(row=row_idx, column=0, padx=10, pady=6, sticky="w")
            
            state_var = tk.StringVar(value="UNKNOWN")
            state_label = ctk.CTkLabel(parent_frame, textvariable=state_var, width=80, height=26, fg_color="#444444", text_color="white", corner_radius=6, font=("Arial", 10, "bold"))
            state_label.grid(row=row_idx, column=1, padx=5, pady=6)
            
            on_btn = ctk.CTkButton(parent_frame, text="ON", width=70, height=26, fg_color=MATTE_GREEN, hover_color=MATTE_GREEN_HOVER, command=lambda ch=channel: self.send_command(f"SET {ch} ON"))
            on_btn.grid(row=row_idx, column=2, padx=(5,2), pady=6, sticky="ew")
            
            off_btn = ctk.CTkButton(parent_frame, text="OFF", width=70, height=26, fg_color=MATTE_RED, hover_color=MATTE_RED_HOVER, command=lambda ch=channel: self.send_command(f"SET {ch} OFF"))
            off_btn.grid(row=row_idx, column=3, padx=(2,5), pady=6, sticky="ew")
            
            # НОВА КОЛОНА: Измерване на ток
            current_var = tk.StringVar(value="0.00 A")
            current_label = ctk.CTkLabel(parent_frame, textvariable=current_var, width=80, height=26, fg_color="#3a3a3a", text_color="white", corner_radius=6, font=("Arial", 10, "bold"))
            current_label.grid(row=row_idx, column=4, padx=5, pady=6)
            
            # Колона Температура (Преместена на колона 5)
            overtemp_label = ctk.CTkLabel(parent_frame, text="Standby", width=90, height=26, fg_color=MATTE_GRAY, text_color="white", corner_radius=6, font=("Arial", 9, "bold"))
            overtemp_label.grid(row=row_idx, column=5, padx=10, pady=6)
            
            parent_frame.grid_columnconfigure(2, weight=1)
            parent_frame.grid_columnconfigure(3, weight=1)
            parent_frame.grid_columnconfigure(4, weight=1)
            
            self.state_vars[name] = state_var
            self.state_labels[name] = state_label
            self.solenoid_current_vars[name] = current_var
            self.solenoid_current_labels[name] = current_label
            self.overtemp_labels[name] = overtemp_label
            self.solenoid_buttons.extend([on_btn, off_btn])

        for group_name, solenoid_list in PISTON_GROUPS.items():
            group_frame = ctk.CTkFrame(solenoid_frame, fg_color="#2b2b2b", corner_radius=6)
            group_frame.grid(row=current_row, column=0, columnspan=6, sticky="ew", padx=10, pady=(10, 5))
            group_frame.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(group_frame, text=group_name, font=("Arial", 12, "bold"), text_color=MATTE_BLUE).grid(row=0, column=0, columnspan=6, pady=(5,5), sticky="w", padx=10)
            
            for i, sol_name in enumerate(solenoid_list):
                create_solenoid_row(group_frame, sol_name, i + 1)
            
            current_row += 1

        if OTHER_SOLENOIDS:
            other_frame = ctk.CTkFrame(solenoid_frame, fg_color="#2b2b2b", corner_radius=6)
            other_frame.grid(row=current_row, column=0, columnspan=6, sticky="ew", padx=10, pady=(10, 5))
            ctk.CTkLabel(other_frame, text="Other Solenoids", font=("Arial", 12, "bold"), text_color=MATTE_BLUE).grid(row=0, column=0, columnspan=6, pady=(5,5), sticky="w", padx=10)
            for i, sol_name in enumerate(OTHER_SOLENOIDS):
                 create_solenoid_row(other_frame, sol_name, i + 1)
            current_row +=1

    def build_sensor_panel(self, parent):
        sensor_frame = ctk.CTkFrame(parent, corner_radius=10)
        sensor_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        sensor_frame.columnconfigure(0, weight=1)
        self.sensor_canvases = []
        for i in range(len(SENSOR_DISPLAY_CONFIG)):
            sensor_frame.grid_rowconfigure(i, weight=1)
            
        for i, (title, channel) in enumerate(SENSOR_DISPLAY_CONFIG):
            card_frame = ctk.CTkFrame(sensor_frame, fg_color="#2b2b2b", corner_radius=8)
            card_frame.grid(row=i, column=0, pady=4, padx=10, sticky="nsew") 
            ctk.CTkLabel(card_frame, text=title, font=("Arial", 12, "bold")).pack(pady=(4, 2))
            
            row_frame = ctk.CTkFrame(card_frame, fg_color="transparent")
            row_frame.pack(fill="x", expand=True, padx=10, pady=(0, 4))
            value_var = tk.StringVar(value="---")
            value_label = ctk.CTkLabel(row_frame, textvariable=value_var, width=120, height=35, fg_color="#444444", text_color="white", corner_radius=6, font=("Arial", 16, "bold"))
            value_label.pack(side="left", padx=(0, 10))
            canvas = tk.Canvas(row_frame, height=40, bg="#2b2b2b", highlightthickness=0)
            canvas.pack(side="right", fill="x", expand=True)
            self.sensor_canvases.append(canvas)
            self.sensor_value_vars.append(value_var)
            self.sensor_value_labels.append(value_label)
            self.sensor_channel_to_widget[channel] = i
            self.draw_sensor_gauge(i, "---")
            
        self.check_sensors_btn = ctk.CTkButton(sensor_frame, text="Check Sensors", height=40, font=("Arial", 12, "bold"), width=180, command=self.start_sensor_check)
        sensor_frame.grid_rowconfigure(len(SENSOR_DISPLAY_CONFIG), weight=0)
        self.check_sensors_btn.grid(row=len(SENSOR_DISPLAY_CONFIG), column=0, pady=(10, 10), padx=10)

    # Чертане на скалите за сензорите с показателите ОТДОЛУ
    def draw_sensor_gauge(self, index, value_text):
        canvas = self.sensor_canvases[index]
        canvas.update()
        h = canvas.winfo_height()
        if h <= 1: h = 40
        bar_h = 16 
        y_start = (h/2) - (bar_h/2) - 4
        canvas.delete("all")
        
        # --- Конфигурация на скалите ---
        min_range, max_range, min_ok, max_ok = 50, 90, 65, 75 
        if index == 4: 
            min_range, max_range, min_ok, max_ok = 700, 1200, 950, 1100
        elif index == 5: 
            min_range, max_range, min_ok, max_ok = 5000, 7000, 5400, 6400
        w_pixels, x_offset = 420, 15
        
        def val_to_x(val):
            if (max_range - min_range) == 0: return x_offset
            return x_offset + max(0, min(1, (val - min_range) / (max_range - min_range))) * w_pixels

        # Основна сива лента
        canvas.create_rectangle(x_offset, y_start, x_offset + w_pixels, y_start + bar_h, fill="#444444", outline="")
        
        # Зелена "ОК" зона
        canvas.create_rectangle(val_to_x(min_ok), y_start, val_to_x(max_ok), y_start + bar_h, fill=MATTE_GREEN, outline="")
        
        # Текст под скалата (форматиран за kΩ)
        def format_label(val):
            return f"{val/1000.0:.1f}k" if val >= 1000 else str(val)
        
        text_y_pos = y_start + bar_h + 10 
        canvas.create_text(val_to_x(min_range), text_y_pos, text=format_label(min_range), fill="#888888", font=("Arial", 9), anchor="w")
        canvas.create_text(val_to_x(max_range), text_y_pos, text=format_label(max_range), fill="#888888", font=("Arial", 9), anchor="e")
        
        # Рисуване на ОК зоната отдолу
        canvas.create_text(val_to_x(min_ok), text_y_pos, text=format_label(min_ok), fill="#cccccc", font=("Arial", 9, "bold"))
        canvas.create_text(val_to_x(max_ok), text_y_pos, text=format_label(max_ok), fill="#cccccc", font=("Arial", 9, "bold"))

        try:
            val = float(value_text.split()[0])
            display_val = max(min_range, min(max_range, val))
            x = val_to_x(display_val)
            
            canvas.create_line(x, y_start - 3, x, y_start + bar_h + 3, fill="white", width=2)
            canvas.create_polygon(x-4, y_start - 4, x+4, y_start - 4, x, y_start, fill="white")
        except (ValueError, IndexError): 
            pass

    def build_inductance_panel(self, parent):
        inductance_frame = ctk.CTkFrame(parent, corner_radius=10)
        inductance_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        inductance_frame.columnconfigure(0, weight=1)
        for i in range(len(INDUCTANCE_DISPLAY_CONFIG)):
            inductance_frame.grid_rowconfigure(i, weight=1)
        for i, config in enumerate(INDUCTANCE_DISPLAY_CONFIG):
            self.create_inductance_card(inductance_frame, i, config, "full", self.full_inductance_vars)
        self.check_positions_btn = ctk.CTkButton(inductance_frame, text="Check Positions", height=40, font=("Arial", 12, "bold"), width=180, command=self.start_inductance_check)
        inductance_frame.grid_rowconfigure(len(INDUCTANCE_DISPLAY_CONFIG), weight=0)
        self.check_positions_btn.grid(row=len(INDUCTANCE_DISPLAY_CONFIG), column=0, pady=(15, 10), padx=10)

    def build_simple_inductance_panel(self, parent, widget_vars, text, sticky, col=1, row=0):
        inductance_frame = ctk.CTkFrame(parent, corner_radius=10)
        inductance_frame.grid(row=row, column=col, sticky=sticky, padx=10, pady=10)
        inductance_frame.columnconfigure(0, weight=1)
        ctk.CTkLabel(inductance_frame, text=text, font=("Arial", 11, "bold")).grid(row=0, column=0, pady=5)
        inductance_frame.grid_rowconfigure(0, weight=0)
        for i in range(len(INDUCTANCE_DISPLAY_CONFIG)):
            inductance_frame.grid_rowconfigure(i + 1, weight=1)
        for i, config in enumerate(INDUCTANCE_DISPLAY_CONFIG):
            self.create_inductance_card(inductance_frame, i + 1, config, "simple", widget_vars)
    
    def build_test_results_panel(self, parent):
        results_frame = ctk.CTkFrame(parent, corner_radius=10)
        results_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=(10, 0))
        results_frame.grid_rowconfigure(1, weight=1)
        results_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(results_frame, text="Test Results", font=("Arial", 11, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.test_results_textbox = ctk.CTkTextbox(results_frame, height=100, font=("Consolas", 10), state="disabled", wrap="word")
        self.test_results_textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def create_inductance_card(self, parent, index, config, panel_type, widget_vars):
        title, channel, _, _, _, _, _, _ = config
        is_full = panel_type == "full"
        card_pady = 10
        
        card_frame = ctk.CTkFrame(parent, fg_color="#2b2b2b", corner_radius=8)
        card_frame.grid(row=index, column=0, pady=card_pady, padx=10, sticky="nsew")
        
        ctk.CTkLabel(card_frame, text=title, font=("Arial", 14, "bold")).pack(pady=(8, 4))
        
        row_frame = ctk.CTkFrame(card_frame, fg_color="transparent")
        row_frame.pack(fill="x", expand=True, padx=10, pady=(0, 8))
        
        target_index = index if is_full else index - 1
        value_var = widget_vars["vars"][target_index]
        value_label = ctk.CTkLabel(row_frame, textvariable=value_var, width=140, height=45, fg_color="#444444", text_color="white", corner_radius=6, font=("Arial", 18, "bold"))
        value_label.pack(side="left", padx=(0, 10))
        canvas = tk.Canvas(row_frame, height=80, bg="#2b2b2b", highlightthickness=0)
        canvas.pack(side="right", fill="x", expand=True)
        widget_vars["labels"][target_index] = value_label
        widget_vars["canvases"][target_index] = canvas
        widget_vars["channel_map"][channel] = target_index
        if is_full:
            control_buttons_frame = ctk.CTkFrame(card_frame, fg_color="transparent")
            control_buttons_frame.pack(fill="x", pady=(4, 8), padx=10)
            solenoid_map = PISTON_SOLENOID_MAP.get(channel, {})
            out_text = f"🟢 {solenoid_map.get('OUT', 'MAX OUT')}"
            in_text = f"🔵 {solenoid_map.get('IN', 'MAX IN')}"
            out_btn = ctk.CTkButton(control_buttons_frame, text=out_text, height=35, font=("Arial", 12, "bold"), fg_color=MATTE_GREEN, hover_color=MATTE_GREEN_HOVER, command=lambda ch=channel: self.move_piston_and_read(ch, "OUT"))
            out_btn.pack(side="left", fill="x", expand=True, padx=(0, 3))
            in_btn = ctk.CTkButton(control_buttons_frame, text=in_text, height=35, font=("Arial", 12, "bold"), fg_color=MATTE_BLUE, hover_color=MATTE_BLUE_HOVER, command=lambda ch=channel: self.move_piston_and_read(ch, "IN"))
            in_btn.pack(side="right", fill="x", expand=True, padx=(3, 0))
            self.individual_piston_buttons.extend([out_btn, in_btn])
        
        self.draw_piston_gauge(target_index, "---", widget_vars)

    def move_piston_and_read(self, channel, direction):
        self.send_command(f"P_{direction} {channel}")
        self.root.after(1000, lambda: self.start_single_inductance_check(channel))

    def draw_piston_gauge(self, index, value_text, widget_vars):
        canvas = widget_vars["canvases"][index]
        if not canvas: return
        canvas.update()
        h, bar_h = canvas.winfo_height(), PISTON_GAUGE_HEIGHT
        y_start = (h/2) - (bar_h/2)
        canvas.delete("all")
        _, _, min_val, in_start, in_end, out_start, out_end, max_val = INDUCTANCE_DISPLAY_CONFIG[index]
        w_pixels, x_offset = 500, 15
        def val_to_x(val): return x_offset + max(0, min(1, (val - min_val) / float(max_val - min_val))) * w_pixels
        canvas.create_rectangle(x_offset, y_start, x_offset + w_pixels, y_start + bar_h, fill="#444444", outline="")
        x_out_start, x_out_end = val_to_x(out_start), val_to_x(out_end)
        canvas.create_rectangle(x_out_start, y_start, x_out_end, y_start + bar_h, fill=MATTE_GREEN, outline="")
        x_in_start, x_in_end = val_to_x(in_start), val_to_x(in_end)
        canvas.create_rectangle(x_in_start, y_start, x_in_end, y_start + bar_h, fill=MATTE_GREEN, outline="")
        
        canvas.create_text(x_offset, y_start + bar_h + 10, text=f"{min_val:.0f}", fill="#888888", font=("Arial", 11))
        canvas.create_text((x_in_start + x_in_end)/2, y_start + bar_h + 10, text=f"IN: {in_start:.2f}-{in_end:.2f}", fill="#cccccc", font=("Arial", 11, "bold"))
        canvas.create_text((x_out_start + x_out_end)/2, y_start + bar_h + 10, text=f"OUT: {out_start:.2f}-{out_end:.2f}", fill="#cccccc", font=("Arial", 11, "bold"))
        canvas.create_text(x_offset + w_pixels, y_start + bar_h + 10, text=f"{max_val:.0f}", fill="#888888", font=("Arial", 11))
        try:
            val = float(value_text.split()[0])
            display_val = max(min_val, min(max_val, val))
            x = val_to_x(display_val)
            canvas.create_line(x, y_start - 5, x, y_start + bar_h + 5, fill="white", width=2)
            canvas.create_polygon(x-5, y_start - 5, x+5, y_start - 5, x, y_start)
        except (ValueError, IndexError): pass

    def build_tests_panel(self, parent):
        tests_frame = ctk.CTkFrame(parent, corner_radius=10)
        tests_frame.pack(pady=(0, 10), fill="x")
        for idx, test_name in enumerate(TEST_NAMES):
            btn = ctk.CTkButton(tests_frame, text=f"Test {test_name}", height=30, command=lambda name=test_name: self.run_test(name))
            btn.pack(fill="x", padx=4, pady=2)
            self.predefined_buttons.append(btn)

    def build_auto_panel(self, parent):
        auto_frame = ctk.CTkFrame(parent, corner_radius=10)
        auto_frame.pack(fill="both", expand=True)
        auto_frame.columnconfigure((0, 1), weight=1)
        auto_frame.rowconfigure(2, weight=1)
        self.auto_start_btn = ctk.CTkButton(auto_frame, text="Start Auto Sequence", fg_color=MATTE_GREEN, hover_color=MATTE_GREEN_HOVER, command=self.start_auto_sequence)
        self.auto_start_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.auto_stop_btn = ctk.CTkButton(auto_frame, text="Stop Auto Sequence", fg_color=MATTE_RED, hover_color=MATTE_RED_HOVER, command=self.stop_auto_sequence)
        self.auto_stop_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.auto_progress = ttk.Progressbar(auto_frame, orient="horizontal", mode="determinate", maximum=len(TEST_NAMES))
        self.auto_progress.grid(row=1, column=0, columnspan=2, padx=5, pady=10, sticky="ew")
        self.sequence_listbox = tk.Listbox(auto_frame, font=("Consolas", 10), bg="#222222", fg="white", selectbackground=MATTE_BLUE, bd=0, highlightthickness=0)
        self.sequence_listbox.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")

    # --- СТРАНИЦА: HISTORY PLOT (С табове за Сензори и Бутала) ---
    def build_history_plot_page(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        if not HAS_MATPLOTLIB:
            ctk.CTkLabel(parent, text="Matplotlib library not found.\nPlease install it via 'pip install matplotlib' to see charts.",
                         font=("Arial", 16)).pack(expand=True)
            return

        # Създаване на табовете
        tabview = ctk.CTkTabview(parent, segmented_button_selected_color=MATTE_BLUE)
        tabview.grid(row=0, column=0, sticky="nsew", padx=10, pady=5)
        
        tab_sensors = tabview.add("📊 Resistive Sensors")
        tab_pistons = tabview.add("⚙️ Piston Positions")
        
        for r in range(3): tab_sensors.grid_rowconfigure(r, weight=1)
        for c in range(2): tab_sensors.grid_columnconfigure(c, weight=1)
        for r in range(2): tab_pistons.grid_rowconfigure(r, weight=1)
        for c in range(2): tab_pistons.grid_columnconfigure(c, weight=1)

        plt.style.use('dark_background')

        for i, (sensor_name, _) in enumerate(SENSOR_DISPLAY_CONFIG):
            row, col = i // 2, i % 2
            chart_frame = ctk.CTkFrame(tab_sensors, fg_color="#2b2b2b", corner_radius=8)
            chart_frame.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
            chart_frame.grid_columnconfigure(0, weight=1)
            chart_frame.grid_rowconfigure(0, weight=1)

            fig = Figure(figsize=(5, 2.2), dpi=100); fig.patch.set_facecolor("#2b2b2b")
            ax = fig.add_subplot(111); ax.set_facecolor("#3c3c3c")
            canvas = FigureCanvasTkAgg(fig, master=chart_frame)
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=2, pady=2)
            
            self.history_all_widgets[sensor_name] = {"fig": fig, "ax": ax, "canvas": canvas}
            self.update_history_chart(sensor_name)

        for i, config in enumerate(INDUCTANCE_DISPLAY_CONFIG):
            piston_name = config[0]
            row, col = i // 2, i % 2
            chart_frame = ctk.CTkFrame(tab_pistons, fg_color="#2b2b2b", corner_radius=8)
            chart_frame.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
            chart_frame.grid_columnconfigure(0, weight=1)
            chart_frame.grid_rowconfigure(0, weight=1)

            fig = Figure(figsize=(5, 3.2), dpi=100); fig.patch.set_facecolor("#2b2b2b")
            ax = fig.add_subplot(111); ax.set_facecolor("#3c3c3c")
            canvas = FigureCanvasTkAgg(fig, master=chart_frame)
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=2, pady=2)
            
            self.history_all_widgets[piston_name] = {"fig": fig, "ax": ax, "canvas": canvas}
            self.update_history_chart(piston_name)

    # --- СТРАНИЦА: AI DIAGNOSTICS ---
    def build_ai_diagnostics_page(self, parent):
        parent.grid_columnconfigure(0, weight=0)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        ai_control_frame = ctk.CTkFrame(parent, width=320, corner_radius=10, fg_color="#18181a")
        ai_control_frame.grid(row=0, column=0, sticky="ns", padx=10, pady=10)
        ai_control_frame.pack_propagate(False)

        ctk.CTkLabel(ai_control_frame, text="🧠 AI Sensor Diagnosis", font=("Arial", 16, "bold"), text_color=MATTE_BLUE).pack(pady=20)
        
        self.auto_test_btn = ctk.CTkButton(ai_control_frame, text="⚡ Run AI Sensor Test (10x)", fg_color=MATTE_GREEN, hover_color=MATTE_GREEN_HOVER, command=self.start_sensor_history_auto_test)
        self.auto_test_btn.pack(pady=15, padx=20, fill="x")

        self.auto_test_progress = ctk.CTkProgressBar(ai_control_frame)
        self.auto_test_progress.pack(pady=10, padx=20, fill="x")
        self.auto_test_progress.set(0.0)

        self.auto_test_status_label = ctk.CTkLabel(ai_control_frame, text="Status: Ready", font=("Arial", 12, "bold"))
        self.auto_test_status_label.pack(pady=10)

        report_frame = ctk.CTkFrame(parent, corner_radius=10)
        report_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        report_frame.grid_columnconfigure(0, weight=1)
        report_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(report_frame, text="📋 Diagnostic Report Analysis", font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="w", padx=15, pady=10)

        self.ai_report_textbox = ctk.CTkTextbox(report_frame, font=("Consolas", 11), wrap="word")
        self.ai_report_textbox.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        self.ai_report_textbox.insert("1.0", "Изпълнете 10-кратния автоматичен тест вляво, за да генерирате AI доклад за състоянието на сензорите...")
        self.ai_report_textbox.configure(state="disabled")
    
    # --- ФУНКЦИИ ЗА АВТОМАТИЧНИЯ ТЕСТ НА СЕНЗОРИТЕ ---
    def start_sensor_history_auto_test(self):
        if self.auto_test_running:
            return
            
        self.auto_test_running = True
        self.auto_test_counter = 0
        self.auto_test_btn.configure(state="disabled")
        self.auto_test_progress.set(0.0)
        self.auto_test_status_label.configure(text="Инициализация...")
        
        for sensor_name, _ in SENSOR_DISPLAY_CONFIG:
            if sensor_name in self.history_data:
                self.history_data[sensor_name].clear()
            else:
                self.history_data[sensor_name] = []
            self.update_history_chart(sensor_name)
            
        self.run_next_auto_test_step()

    def run_next_auto_test_step(self):
        if not self.auto_test_running:
            return
            
        if self.auto_test_counter < self.auto_test_max_runs:
            progress_val = self.auto_test_counter / self.auto_test_max_runs
            self.auto_test_progress.set(progress_val)
            self.auto_test_status_label.configure(text=f"Измерване: {self.auto_test_counter + 1}/{self.auto_test_max_runs}")
            self.start_sensor_check()
            self.auto_test_counter += 1
        else:
            self.auto_test_running = False
            self.auto_test_progress.set(1.0)
            self.auto_test_status_label.configure(text="Анализиране...")
            self.root.after(500, self.run_ai_analysis)

    # --- 🧠 УМНИЯТ АНАЛИЗАТОР НА СЕНЗОРИТЕ (AI ENGINE) ---
    def run_ai_analysis(self):
        try:
            report = []
            report.append("==================================================")
            report.append("🧠 ZF GS3 TCU - ИЗКУСТВЕН ИНТЕЛЕКТ ДИАГНОСТИЧЕН ДОКЛАД")
            report.append(f"Дата/Час на анализа: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            report.append(f"Сериен номер на TCU: {self.serial_var.get().strip() or 'N/A'}")
            report.append("==================================================\n")
            
            passed_sensors = 0
            total_sensors = len(SENSOR_DISPLAY_CONFIG)
            detailed_analysis = []
            
            for idx, (sensor_name, channel) in enumerate(SENSOR_DISPLAY_CONFIG):
                history = self.history_data.get(sensor_name, [])
                min_ok, max_ok = (65.0, 75.0) if idx < 4 else (950.0, 1100.0) if idx == 4 else (5400.0, 6400.0)
                    
                if not history or len(history) < self.auto_test_max_runs:
                    detailed_analysis.append(f"❌ {sensor_name}: НЕДОСТАТЪЧНО ДАННИ\n   -> Не са получени {self.auto_test_max_runs} измервания. Изпълнете теста отново.\n")
                    continue
                    
                timestamps, values = zip(*history)
                has_open = any(v < 0 or v > 20000 for v in values)
                
                if has_open:
                    detailed_analysis.append(f"🔴 {sensor_name}: ПРЕКЪСНАТА ВЕРИГА\n   -> Препоръка: Проверете пиновете и окабеляването.\n")
                    continue
                    
                avg_val = sum(values) / len(values)
                variance_pct = ((max(values) - min(values)) / avg_val) * 100 if avg_val > 0 else 0
                
                status_str, action_str = "", ""
                
                if avg_val < 5.0:
                    status_str = "🔴 КЪСО СЪЕДИНЕНИЕ"
                    action_str = "-> Риск от повреда! Сменете датчика веднага."
                elif min_ok <= avg_val <= max_ok:
                    if variance_pct > 5.0:
                        status_str = "⚠️ НЕСТАБИЛЕН"
                        action_str = f"-> Анализ: Ср. стойност {avg_val:.1f}Ω е в норма, но има голям шум/колебания. Проверете буксата."
                    else:
                        status_str = "🟢 ПЕРФЕКТЕН"
                        action_str = f"-> Анализ: Ср. стойност {avg_val:.1f}Ω. Стабилен сигнал."
                        passed_sensors += 1
                else:
                    status_str = "🟡 ИЗВЪН НОРМА"
                    action_str = f"-> Анализ: Стойност {avg_val:.1f}Ω е извън спецификация ({min_ok:.0f}-{max_ok:.0f}Ω). Препоръчва се подмяна."
                
                detailed_analysis.append(f"• {sensor_name}: {status_str}\n   {action_str}\n")

            health_pct = (passed_sensors / total_sensors) * 100 if total_sensors > 0 else 0
            report.append(f"📊 ОБЩА ОЦЕНКА: {health_pct:.1f}%")
            report.append(f"Резултат: {passed_sensors} от {total_sensors} сензора преминаха теста успешно.\n")
            report.append("--------------------------------------------------")
            report.append("ПОДРОБЕН АНАЛИЗ ПО КОМПОНЕНТИ:")
            report.append("--------------------------------------------------")
            report.extend(detailed_analysis)
            
            final_report_text = "\n".join(report)

        except Exception as e:
            final_report_text = f"Грешка по време на анализа: {e}\n\nПроверете дали всички данни са получени коректно."

        self.ai_report_textbox.configure(state="normal")
        self.ai_report_textbox.delete("1.0", "end")
        self.ai_report_textbox.insert("1.0", final_report_text)
        self.ai_report_textbox.configure(state="disabled")
        
        self.auto_test_status_label.configure(text="Диагностиката приключи")
        self.auto_test_btn.configure(state="normal")

    def update_history_chart(self, component_name):
        if not HAS_MATPLOTLIB or component_name not in self.history_all_widgets:
            return
            
        widgets = self.history_all_widgets[component_name]
        fig, ax, canvas = widgets["fig"], widgets["ax"], widgets["canvas"]
        
        ax.clear()
        
        history = self.history_data.get(component_name, [])
        
        is_piston = "Piston" in component_name
        unit = "mH" if is_piston else "Ω"
        
        if history:
            timestamps, values = zip(*history)
            time_labels = [t.strftime('%H:%M:%S') for t in timestamps]
            
            ax.plot(time_labels, values, marker='o', linestyle='-', color='#00aaff', linewidth=2)
            
            for i, value in enumerate(values):
                ax.text(i, value, f' {value:.1f}{unit}', va='bottom', ha='center', color='white', fontsize=8, fontweight='bold')
            
            ax.grid(True, which='both', linestyle='--', linewidth=0.5, color='#555555')
        else:
            ax.text(0.5, 0.5, "No data yet", ha='center', va='center', transform=ax.transAxes, color='grey', fontsize=11)
            
        ax.set_title(f"{component_name}", color='white', fontsize=11, pad=8, fontweight='bold')
        ax.tick_params(axis='x', labelrotation=15, labelsize=8, colors='white')
        ax.tick_params(axis='y', labelsize=8, colors='white')
        fig.tight_layout()
        canvas.draw()
        
    def build_log_panel(self, parent):
        log_frame = ctk.CTkFrame(parent, corner_radius=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(log_frame, font=("Consolas", 10), bg="#1e1e1e", fg="#9cdcfe", bd=0, highlightthickness=0, insertbackground="white", state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def start_sensor_check(self):
        self.log(f"--- SENSOR CHECK for Serial: {self.serial_var.get().strip() or 'N/A'} ---")
        for i, label in enumerate(self.sensor_value_labels):
            self.sensor_value_vars[i].set("Waiting...")
            label.configure(fg_color="orange", text_color="black")
        self.send_command("READSENSORS")

    def start_inductance_check(self):
        self.log(f"--- INDUCTANCE CHECK for Serial: {self.serial_var.get().strip() or 'N/A'} ---")
        for i, label in enumerate(self.full_inductance_vars["labels"]):
            if label:
                self.full_inductance_vars["vars"][i].set("Waiting...")
                label.configure(fg_color="orange", text_color="black")
        self.send_command("READINDUCTANCE")

    def start_single_inductance_check(self, channel):
        self.log(f"--- SINGLE INDUCTANCE CHECK (CH {channel}) for Serial: {self.serial_var.get().strip() or 'N/A'} ---")
        if (widget_index := self.full_inductance_vars["channel_map"].get(channel)) is not None:
            if self.full_inductance_vars["labels"][widget_index]:
                self.full_inductance_vars["vars"][widget_index].set("Waiting...")
                self.full_inductance_vars["labels"][widget_index].configure(fg_color="orange", text_color="black")
        self.send_command(f"READINDUCTANCE {channel}")

    def _manage_sidebar_blink(self):
        if self.blinker_after_id:
            self.root.after_cancel(self.blinker_after_id)
            self.blinker_after_id = None
        current_active_button_color = self.btn_manual_solenoids.cget("fg_color")
        is_on_manual_page = current_active_button_color == MATTE_BLUE
        if self.sidebar_alert_level == 0:
            normal_color = MATTE_BLUE if is_on_manual_page else "transparent"
            self.btn_manual_solenoids.configure(text=self.original_sidebar_text, fg_color=normal_color)
            return
        self.sidebar_blink_state = 1 - self.sidebar_blink_state
        if self.sidebar_alert_level == 1:
            text_to_show = f"{self.original_sidebar_text} ⚠️" if self.sidebar_blink_state == 1 else self.original_sidebar_text
            self.btn_manual_solenoids.configure(text=text_to_show, fg_color="transparent")
        elif self.sidebar_alert_level == 2:
            color_to_show = MATTE_RED if self.sidebar_blink_state == 1 else "transparent"
            self.btn_manual_solenoids.configure(text=f"{self.original_sidebar_text} ⚠️", fg_color=color_to_show)
        self.blinker_after_id = self.root.after(500, self._manage_sidebar_blink)

    def check_overtemp(self):
        current_time = time.time()
        max_level_this_cycle = 0
        for name, start_time in list(self.solenoid_on_times.items()):
            on_duration = current_time - start_time
            label = self.overtemp_labels[name]
            if on_duration > OVERTEMP_CRIT_SECONDS:
                label.configure(text="OVERTEMP", fg_color=MATTE_RED)
                max_level_this_cycle = 2
            elif on_duration > OVERTEMP_WARN_SECONDS:
                label.configure(text="Warning", fg_color="orange", text_color="black")
                max_level_this_cycle = max(max_level_this_cycle, 1)
            else:
                label.configure(text="OK", fg_color=MATTE_GREEN, text_color="white")
        if max_level_this_cycle != self.sidebar_alert_level:
            self.sidebar_alert_level = max_level_this_cycle
            self._manage_sidebar_blink()
        self.root.after(2000, self.check_overtemp)

    def set_state(self, channel, state):
        if not (0 <= (index := channel - 1) < len(SOLENOID_NAMES)): return
        
        name = SOLENOID_NAMES[index]
        self.current_states[index] = state
        self.state_vars[name].set(state)
        self.state_labels[name].configure(fg_color=MATTE_GREEN if state == "ON" else MATTE_RED if state == "OFF" else "#444444")
        
        if state == "ON":
            if name not in self.solenoid_on_times: self.solenoid_on_times[name] = time.time()
        else:
            if name in self.solenoid_on_times:
                del self.solenoid_on_times[name]
                self.overtemp_labels[name].configure(text="Standby", fg_color=MATTE_GRAY)
                if not self.solenoid_on_times:
                    if self.sidebar_alert_level != 0:
                        self.sidebar_alert_level = 0
                        self._manage_sidebar_blink()

    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo.configure(values=ports)
        if ports: self.port_combo.set(ports[0])
        self.log(f"Available ports: {ports or 'None'}")

    def connect_serial(self):
        if self.ser and self.ser.is_open: return self.log("Already connected.")
        if not (port := self.port_var.get()): return messagebox.showwarning("Warning", "Please select a COM port.")
        try:
            self.ser = serial.Serial(port, 115200, timeout=0.1)
            self.connection_var.set(f"Connected to {port}")
            self.log(f"Connected to {port}")
            self.root.after(1000, self.post_connect_setup)
        except Exception as e: messagebox.showerror("Connection Error", str(e))
        self.update_interlock_states()

    def post_connect_setup(self): self.request_full_status()
    
    def disconnect_serial(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.connection_var.set("Disconnected")
            self.mode_var.set("Mode: Unknown")
            self.auto_state_var.set("Auto sequence: STOPPED")
            self.auto_current_var.set("Current step: -")
            self.reset_solenoid_states()
            self.reset_all_cards()
            self.log("Disconnected")
        self.update_interlock_states()

    def send_command(self, cmd):
        if not (self.ser and self.ser.is_open):
            if "SETOFF ALL" not in cmd: messagebox.showwarning("Warning", "Not connected to Arduino.")
            return
        try:
            self.ser.write((cmd + "\n").encode("utf-8"))
            self.log(f"PC -> Arduino: {cmd}")
        except Exception as e: messagebox.showerror("Send Error", str(e))

    def request_full_status(self): 
        self.send_command("GETMODE")
        self.send_command("GETALL")
        
    def run_test(self, test_name):
        self.send_command(f"TEST {test_name}")
        
    def start_auto_sequence(self):
        self.reset_all_cards()
        self.reset_auto_sequence_view()
        self.log(f"--- AUTO SEQUENCE START for Serial: {self.serial_var.get().strip() or 'N/A'} ---")
        self.update_test_results("Starting auto-sequence...")
        self.send_command("AUTO START")
        
    def stop_auto_sequence(self): 
        self.send_command("AUTO STOP")
        self.update_test_results("Auto-sequence stopped by user.")

    def reset_auto_sequence_view(self):
        self.auto_sequence_states, self.last_auto_step_name, self.auto_progress["value"] = ["pending"] * len(TEST_NAMES), "-", 0
        self.auto_state_var.set("Auto sequence: STARTING...")
        self.auto_current_var.set("Current step: -")
        self.refresh_auto_sequence_list()

    def refresh_auto_sequence_list(self):
        self.sequence_listbox.delete(0, tk.END)
        current_index = -1
        for idx, test_name in enumerate(TEST_NAMES):
            prefix = {"done": "[x]", "current": "[>]"}.get(self.auto_sequence_states[idx], "[ ]")
            if self.auto_sequence_states[idx] == "current": current_index = idx
            self.sequence_listbox.insert(tk.END, f"{prefix} Test {test_name}")
        if current_index != -1:
            self.sequence_listbox.selection_clear(0, tk.END)
            self.sequence_listbox.selection_set(current_index)
            self.sequence_listbox.see(current_index)

    def update_auto_step(self, step_number, total_steps, test_name):
        if not (0 <= (step_index := step_number - 1) < len(TEST_NAMES)): return
        
        if step_index > 0:
            previous_test_name = TEST_NAMES[step_index - 1]
            self.test_statuses[previous_test_name] = "passed"
        
        self.last_auto_step_name = test_name
        for i in range(len(TEST_NAMES)): self.auto_sequence_states[i] = "done" if i < step_index else "current" if i == step_index else "pending"
        self.auto_progress["maximum"], self.auto_progress["value"] = total_steps, step_number
        self.auto_state_var.set("Auto sequence: RUNNING")
        self.auto_current_var.set(f"Current step: {step_number}/{total_steps} - Test {test_name}")
        self.refresh_auto_sequence_list()
        self.send_command("READINDUCTANCE")
        self.update_test_results(f"Running auto-test step {step_number}/{total_steps} (Test {test_name})...")
        self.update_test_button_colors()

    def complete_auto_sequence(self):
        self.auto_sequence_states = ["done"] * len(TEST_NAMES)
        self.auto_progress["value"] = len(TEST_NAMES)
        if self.last_auto_step_name in self.test_statuses:
            self.test_statuses[self.last_auto_step_name] = "passed"
        self.auto_state_var.set("Auto sequence: COMPLETED")
        self.auto_current_var.set(f"Current step: Completed - Last test {self.last_auto_step_name}")
        self.refresh_auto_sequence_list()
        self.update_test_results("Auto-sequence finished. All tests passed (placeholder).")
        self.update_test_button_colors()

    def update_test_results(self, text):
        self.test_results_textbox.configure(state="normal")
        self.test_results_textbox.delete("1.0", "end")
        self.test_results_textbox.insert("1.0", text)
        self.test_results_textbox.configure(state="disabled")

    def update_test_button_colors(self):
        color_map = {"pending": DEFAULT_BTN_COLOR, "passed": MATTE_GREEN, "failed": MATTE_RED}
        for i, test_name in enumerate(TEST_NAMES):
            status = self.test_statuses.get(test_name, "pending")
            if i < len(self.predefined_buttons):
                self.predefined_buttons[i].configure(fg_color=color_map[status])

    def format_ohms_value(self, value):
        if value >= 1_000_000: return f"{value / 1_000_000:.2f} MΩ"
        if value >= 1_000: return f"{value / 1_000:.2f} kΩ"
        return f"{value:.0f} Ω"

    def format_resistance(self, value_text):
        try: return self.format_ohms_value(float(value_text))
        except (ValueError, TypeError): return str(value_text)

    def format_pressure(self, value_text):
        try: return f"{float(value_text):.2f} {PRESSURE_SENSOR_CONFIG['unit']}"
        except (ValueError, TypeError): return str(value_text)

    def format_inductance_value(self, value):
        return f"{value / 1000.0:.2f} mH" if value >= 1000.0 else f"{value:.1f} uH"

    def format_inductance(self, value_text):
        try: return self.format_inductance_value(float(value_text))
        except (ValueError, TypeError): return str(value_text)

    def apply_sensor_style(self, widget_index, raw_value):
        label = self.sensor_value_labels[widget_index]
        color = "#444444"
        
        self.draw_sensor_gauge(widget_index, raw_value)
        
        try:
            val = float(raw_value.split()[0])
            min_ok, max_ok = 0, 0
            if widget_index < 4: 
                min_ok, max_ok = 65, 75
            elif widget_index == 4:
                min_ok, max_ok = 950, 1100
            elif widget_index == 5:
                min_ok, max_ok = 5400, 6400
            if min_ok <= val <= max_ok:
                color = MATTE_GREEN
            else:
                color = MATTE_RED
                
        except (ValueError, IndexError, TypeError):
            pass
        
        label.configure(fg_color=color, text_color="white")

    def apply_inductance_style(self, widget_vars, widget_index, raw_value):
        label = widget_vars["labels"][widget_index]
        if not label: return
        
        try:
            val_in_mH = float(raw_value) / 1000.0 
        except (ValueError, TypeError):
            self.draw_piston_gauge(widget_index, "---", widget_vars)
            label.configure(fg_color="#444444", text_color="white")
            return
        self.draw_piston_gauge(widget_index, str(val_in_mH), widget_vars)
        
        color = "#444444"
        try:
            _, _, _, out_start, out_end, in_start, in_end, _ = INDUCTANCE_DISPLAY_CONFIG[widget_index]
            if (in_start <= val_in_mH <= in_end) or (out_start <= val_in_mH <= out_end):
                color = MATTE_GREEN
            else:
                color = MATTE_RED
        except (ValueError, TypeError):
            pass
        
        label.configure(fg_color=color, text_color="white")

    def apply_pressure_style(self, raw_value):
        try:
            float(raw_value)
            self.pressure_value_label.configure(fg_color=MATTE_BLUE)
        except (ValueError, TypeError): self.pressure_value_label.configure(fg_color="#333333")

    # --- НОВИ ФУНКЦИИ ЗА СЛЕДЕНЕ НА СИСТЕМНОТО НАПРЕЖЕНИЕ (24V) ---
    def set_voltage(self, value_text):
        try:
            val = float(value_text)
            self.voltage_value_var.set(f"{val:.2f} V")
            self.apply_voltage_style(value_text)
        except (ValueError, TypeError):
            self.voltage_value_var.set(str(value_text))
            self.apply_voltage_style("---")

    def apply_voltage_style(self, raw_value):
        try:
            val = float(raw_value)
            # Нормален диапазон на захранването: между 21.0V и 27.0V
            if 21.0 <= val <= 27.0:
                self.voltage_value_label.configure(fg_color=MATTE_GREEN) # Матово зелено
            else:
                self.voltage_value_label.configure(fg_color=MATTE_RED) # Матово червено (Аларма)
        except (ValueError, TypeError):
            self.voltage_value_label.configure(fg_color="#333333")

    # --- НОВИ ФУНКЦИИ ЗА СЛЕДЕНЕ НА АМПЕРАЖА (ТОКА) ---
    def set_individual_current(self, channel, value_text):
        if not (1 <= channel <= len(SOLENOID_NAMES)): return
        name = SOLENOID_NAMES[channel - 1]
        var = self.solenoid_current_vars.get(name)
        lbl = self.solenoid_current_labels.get(name)
        if var and lbl:
            try:
                val = float(value_text)
                var.set(f"{val:.2f} A")
                if val > 0.50: # Праг за късо съединение / претоварване
                    lbl.configure(fg_color=MATTE_RED)
                elif val > 0.05: # Клапанът работи нормално
                    lbl.configure(fg_color=MATTE_GREEN)
                else: # Standby
                    lbl.configure(fg_color="#3a3a3a")
            except (ValueError, TypeError):
                var.set(str(value_text))
                lbl.configure(fg_color="#3a3a3a")

    def parse_currents_data(self, args):
        for item in args:
            if len(parts := item.split(':', 1)) == 2 and parts[0].isdigit():
                self.set_individual_current(int(parts[0]), parts[1])

    # --- СВЕТКАВИЧНА РЕАКЦИЯ ПРИ СВРЪХТОК (КЪСО) ---
    def trigger_overcurrent_alarm(self, channel):
        if not (1 <= channel <= len(SOLENOID_NAMES)): return
        name = SOLENOID_NAMES[channel - 1]
        
        # Мигновено спираме системата хардуерно и софтуерно
        self.emergency_stop()
        
        var = self.solenoid_current_vars.get(name)
        lbl = self.solenoid_current_labels.get(name)
        if var and lbl:
            var.set("SHORT!")
            lbl.configure(fg_color=MATTE_RED)
            
        messagebox.showerror("🚨 АЛАРМА СВРЪХТОК", 
                             f"Засечено е критично късо съединение / свръхток на соленоид {name} (Канал {channel})!\n\n"
                             f"Захранването към силовия модул беше изключено веднага за безопасност!")

    def reset_inductance_cards(self, widget_vars):
        for i in range(len(widget_vars["vars"])):
            widget_vars["vars"][i].set("---")
            self.apply_inductance_style(widget_vars, i, "---")

    def reset_solenoid_states(self):
        for name in SOLENOID_NAMES: 
            channel = SOLENOID_NAMES.index(name) + 1
            self.set_state(channel, "UNKNOWN")

    def set_resistance(self, channel, value_text):
        if (idx := self.sensor_channel_to_widget.get(channel)) is None: return
        
        try:
            val = float(value_text)
            sensor_name, _ = SENSOR_DISPLAY_CONFIG[idx]
            
            if sensor_name not in self.history_data:
                self.history_data[sensor_name] = []
            
            self.history_data[sensor_name].append((datetime.datetime.now(), val))
            if len(self.history_data[sensor_name]) > 50:
                self.history_data[sensor_name].pop(0)

            self.update_history_chart(sensor_name)
        except (ValueError, TypeError):
            pass

        self.apply_sensor_style(idx, value_text)
        self.sensor_value_vars[idx].set(self.format_resistance(value_text))
    
    def set_inductance(self, channel, value_text):
        for widget_vars in [self.full_inductance_vars, self.manual_inductance_vars, self.auto_inductance_vars]:
            if (idx := widget_vars["channel_map"].get(channel)) is not None:
                widget_vars["vars"][idx].set(self.format_inductance(value_text))
                self.apply_inductance_style(widget_vars, idx, value_text)
                
        try:
            val = float(value_text)
            val_in_mH = val / 1000.0 
            piston_name = INDUCTANCE_DISPLAY_CONFIG[channel - 1][0]
            
            if piston_name not in self.history_data:
                self.history_data[piston_name] = []
                
            self.history_data[piston_name].append((datetime.datetime.now(), val_in_mH))
            if len(self.history_data[piston_name]) > 50:
                self.history_data[piston_name].pop(0)
                
            self.update_history_chart(piston_name)
        except (ValueError, TypeError):
            pass

    def set_pressure(self, value_text):
        self.pressure_value_var.set(self.format_pressure(value_text))
        self.apply_pressure_style(value_text)

    # --- ОБНОВЕН СЕРИЕН ПАРСЕР С НОВИТЕ КОМАНДИ ---
    def parse_serial_line(self, line):
        self.log(f"Arduino -> PC: {line}")
        parts = line.split()
        if not parts: return
        cmd, *args = parts
        handlers = {
            "SENSORS": self.parse_sensors, 
            "INDUCTANCE": self.parse_inductance_data, 
            "ALL": self.parse_all_states, 
            "PRESSURE": lambda a: self.set_pressure(a[0]) if a else None, 
            "VOLTAGE": lambda a: self.set_voltage(a[0]) if a else None, # НОВО
            "CURRENT": lambda a: self.set_individual_current(int(a[0]), a[1]) if len(a) == 2 and a[0].isdigit() else None, # НОВО
            "CURRENTS": self.parse_currents_data, # НОВО
            "ALARM_OVERCURRENT": lambda a: self.trigger_overcurrent_alarm(int(a[0])) if a and a[0].isdigit() else None, # НОВО
            "SOL": lambda a: self.set_state(int(a[0]), a[1].upper()) if len(a) == 2 and a[0].isdigit() else None, 
            "STATE": lambda a: self.set_state(int(a[0]), a[1].upper()) if len(a) == 2 and a[0].isdigit() else None, 
            "MODE": lambda a: self.mode_var.set(f"Mode: {' '.join(a)}"), 
            "AUTO_STATE": lambda a: self.auto_state_var.set(f"Auto sequence: {' '.join(a).upper()}"), 
            "AUTO_DONE": lambda a: self.complete_auto_sequence(), 
            "AUTO_STEP": lambda a: self.update_auto_step(int(a[0]), int(a[1]), a[2]) if len(a) == 3 and a[0].isdigit() and a[1].isdigit() else None
        }
        if cmd in handlers: handlers[cmd](args)

    def parse_all_states(self, args):
        for item in args:
            if len(parts := item.split(':', 1)) == 2 and parts[0].isdigit(): self.set_state(int(parts[0]), parts[1].upper())

    def parse_sensors(self, args):
        for item in args:
            if len(parts := item.split(':', 1)) == 2 and parts[0].isdigit(): self.set_resistance(int(parts[0]), parts[1])
        
        if hasattr(self, 'auto_test_running') and self.auto_test_running:
            self.root.after(1000, self.run_next_auto_test_step)

    def parse_inductance_data(self, args):
        for item in args:
            if len(parts := item.split(':', 1)) == 2 and parts[0].isdigit(): self.set_inductance(int(parts[0]), parts[1])

    def poll_serial(self):
        if self.ser and self.ser.is_open:
            try:
                while self.ser.in_waiting:
                    if line := self.ser.readline().decode("utf-8", errors="ignore").strip(): self.parse_serial_line(line)
            except Exception as e: self.log(f"Read error: {e}")
        self.root.after(100, self.poll_serial)

    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        try:
            with open("tester_log.txt", "a", encoding="utf-8") as f: f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
        except Exception: pass
        
    def on_closing(self):
        if messagebox.askyesno("Изход", "Наистина ли искате да излезете?"):
            if self.blinker_after_id:
                self.root.after_cancel(self.blinker_after_id)
            if self.ser and self.ser.is_open:
                self.send_command("SETOFF ALL")
                time.sleep(0.1)
                try: self.ser.close()
                except: pass
            if serial_no := self.serial_var.get().strip():
                safe_serial = "".join(c for c in serial_no if c.isalnum() or c in ('-', '_'))
                if safe_serial:
                    new_filename = f"TCU_{safe_serial}_log.txt"
                    try:
                        if os.path.exists(new_filename): os.remove(new_filename)
                        if os.path.exists("tester_log.txt"): os.rename("tester_log.txt", new_filename)
                    except Exception: pass
            self.root.destroy()

if __name__ == "__main__":
    root = ctk.CTk()
    app = SolenoidApp(root)
    root.mainloop()
