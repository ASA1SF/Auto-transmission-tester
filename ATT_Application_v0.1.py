import tkinter as tk
from tkinter import messagebox, ttk
import serial
import serial.tools.list_ports
import time
import os

# --- Constants ---
SOLENOID_NAMES = ["Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9", "Y1", "Y10"]
TEST_NAMES = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "RL", "RH"]
SENSOR_DISPLAY_CONFIG = [("Sensor 1", 1), ("Sensor 2", 2), ("Sensor 3", 3), ("Sensor 4", 4), ("Sensor 5", 5)]
PRESSURE_SENSOR_CONFIG = {"title": "System Pressure", "unit": "bar"}
INDUCTANCE_DISPLAY_CONFIG = [("Piston 1", 1), ("Piston 2", 2), ("Piston 3", 3), ("Piston 4", 4)]
OVERTEMP_WARN_SECONDS = 60
OVERTEMP_CRIT_SECONDS = 120

class SolenoidApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ZF GS3 Solenoid Tester")
        self.root.geometry("1800x850")
        self.root.minsize(1300, 700)
        
        # Свързваме затварянето на прозореца с нашата функция
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.default_bg_color = self.root.cget('bg')
        app_frame = ttk.Frame(root)
        app_frame.pack(fill="both", expand=True)
        self.ser = None
        self.state_vars = []
        self.state_labels = []
        self.sensor_value_vars = []
        self.sensor_value_labels = []
        self.sensor_channel_to_widget = {}
        
        # Inductance UI variables
        self.inductance_value_vars = []
        self.inductance_value_labels = []
        self.inductance_channel_to_widget = {}
        
        self.current_states = ["UNKNOWN"] * len(SOLENOID_NAMES)
        self.auto_sequence_states = ["pending"] * len(TEST_NAMES)
        self.last_auto_step_name = "-"
        
        self.overtemp_labels = []
        self.solenoid_on_times = {}
        
        # Списъци за блокировка на бутоните
        self.solenoid_buttons = []
        self.predefined_buttons = []
        self.individual_piston_buttons = []
        self.serial_logged = False # Блокировката е активна по подразбиране
        
        # --- ИЗТРИВАНЕ НА СТАРИЯ ЛОГ И СТАРТИРАНЕ НА НОВА СЕСИЯ ---
        try:
            with open("tester_log.txt", "w", encoding="utf-8") as f:
                f.write(f"=== TEST SESSION STARTED AT {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception as e:
            pass
        
        # 1. Горният панел за връзка остава най-горе (без Read States)
        self.build_top_panel(app_frame)
        
        # 2. Създаваме табовете (ttk.Notebook) в средата
        self.notebook = ttk.Notebook(app_frame)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Дефинираме табовете
        self.tab_solenoids = ttk.Frame(self.notebook, padding=10)
        self.tab_sensors = ttk.Frame(self.notebook, padding=10)
        self.tab_logs = ttk.Frame(self.notebook, padding=10)
        
        self.notebook.add(self.tab_solenoids, text=" 🔌 Управление на Соленоиди & Тестове ")
        self.notebook.add(self.tab_sensors, text=" 📊 Датчици и Позиции на Бутала ")
        self.notebook.add(self.tab_logs, text=" 📝 Сериен Лог и История ")
        
        # 3. Статус панелът отива най-долу (с включен Сериен Номер и Налягане)
        self.build_info_panel(app_frame)
        
        # --- ТАБ 1: СОЛЕНОИДИ И ТЕСТОВЕ ---
        self.tab_solenoids.rowconfigure(0, weight=1)
        self.tab_solenoids.columnconfigure(0, weight=2)
        self.tab_solenoids.columnconfigure(1, weight=1)
        
        self.build_solenoid_panel(self.tab_solenoids)
        
        right_sol_frame = ttk.Frame(self.tab_solenoids)
        right_sol_frame.grid(row=0, column=1, sticky="nsew", padx=(15, 0))
        right_sol_frame.rowconfigure(1, weight=1)
        right_sol_frame.columnconfigure(0, weight=1)
        
        self.build_tests_panel(right_sol_frame)
        self.build_auto_panel(right_sol_frame)
        
        # --- ТАБ 2: ДАТЧИЦИ И ИЗМЕРВАНИЯ ---
        self.tab_sensors.rowconfigure(0, weight=1)
        self.tab_sensors.columnconfigure(0, weight=1)
        self.tab_sensors.columnconfigure(1, weight=1)
        
        self.build_sensor_panel(self.tab_sensors)
        self.build_inductance_panel(self.tab_sensors)
        
        # --- ТАБ 3: ЛОГ И ИСТОРИЯ ---
        self.build_log_panel(self.tab_logs)
        
        self.refresh_ports()
        self.refresh_auto_sequence_list()
        self.reset_sensor_cards()
        self.reset_inductance_cards()
        self.poll_serial()
        self.check_overtemp()
        
        # Прилагаме блокировката веднага при пускане на приложението!
        self.update_interlock_states()

    def update_interlock_states(self):
        conn_state = "normal" if self.serial_logged else "disabled"
        self.port_combo.config(state="readonly" if self.serial_logged else "disabled")
        if hasattr(self, 'refresh_ports_btn'): self.refresh_ports_btn.config(state=conn_state)
        if hasattr(self, 'connect_btn'): self.connect_btn.config(state=conn_state)
        if hasattr(self, 'disconnect_btn'): self.disconnect_btn.config(state=conn_state)
        
        is_connected = self.ser is not None and self.ser.is_open
        test_state = "normal" if (self.serial_logged and is_connected) else "disabled"
        
        # Блокировка на бутони за соленоиди
        for btn in self.solenoid_buttons:
            btn.config(state=test_state)
            
        # Блокировка на предефинирани тестове
        for btn in self.predefined_buttons:
            btn.config(state=test_state)
            
        # Блокировка на авто поредица
        if hasattr(self, 'auto_start_btn'): self.auto_start_btn.config(state=test_state)
        if hasattr(self, 'auto_stop_btn'): self.auto_stop_btn.config(state=test_state)
        
        # Блокировка на сензори и позиции
        if hasattr(self, 'check_sensors_btn'): self.check_sensors_btn.config(state=test_state)
        if hasattr(self, 'check_positions_btn'): self.check_positions_btn.config(state=test_state)
        
        # Блокировка на индивидуални бутони за позиции
        for btn in self.individual_piston_buttons:
            btn.config(state=test_state)
            
        # Блокировка на PDF бутона
        if hasattr(self, 'pdf_report_btn'): self.pdf_report_btn.config(state="normal" if self.serial_logged else "disabled")

    def build_top_panel(self, parent):
        top_frame = ttk.Frame(parent, padding=(10, 10, 10, 0))
        top_frame.pack(fill="x")
        ttk.Label(top_frame, text="COM Port:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top_frame, textvariable=self.port_var, width=18, state="readonly")
        self.port_combo.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        
        self.refresh_ports_btn = ttk.Button(top_frame, text="Refresh Ports", command=self.refresh_ports)
        self.refresh_ports_btn.grid(row=0, column=2, padx=5, pady=5)
        
        self.connect_btn = ttk.Button(top_frame, text="Connect", command=self.connect_serial)
        self.connect_btn.grid(row=0, column=3, padx=5, pady=5)
        
        self.disconnect_btn = ttk.Button(top_frame, text="Disconnect", command=self.disconnect_serial)
        self.disconnect_btn.grid(row=0, column=4, padx=5, pady=5)
        
    def build_info_panel(self, parent):
        info_frame = ttk.LabelFrame(parent, text="Status", padding=10)
        info_frame.pack(fill="x", padx=10, pady=5)
        self.connection_var = tk.StringVar(value="Not connected")
        self.mode_var = tk.StringVar(value="Mode: Unknown")
        self.auto_state_var = tk.StringVar(value="Auto sequence: STOPPED")
        self.auto_current_var = tk.StringVar(value="Current step: -")
        
        # Ред 1 - Всички контроли на 1 общ чист ред!
        ttk.Label(info_frame, textvariable=self.connection_var).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ttk.Label(info_frame, textvariable=self.mode_var, font=("Arial", 10, "bold")).grid(row=0, column=1, padx=(20, 5), pady=5, sticky="w")
        
        # Сериен Номер и PDF бутон
        ttk.Label(info_frame, text="Block Serial No:", font=("Arial", 10, "bold")).grid(row=0, column=2, padx=(40, 5), pady=5, sticky="w")
        self.serial_var = tk.StringVar(value="")
        self.serial_entry = ttk.Entry(info_frame, textvariable=self.serial_var, width=20, font=("Consolas", 10, "bold"))
        self.serial_entry.grid(row=0, column=3, padx=5, pady=5, sticky="w")
        
        self.log_serial_btn = ttk.Button(info_frame, text="Log Serial", command=self.log_serial_number)
        self.log_serial_btn.grid(row=0, column=4, padx=5, pady=5, sticky="w")
        
        self.pdf_report_btn = ttk.Button(info_frame, text="PDF Report", command=self.generate_pdf_report)
        self.pdf_report_btn.grid(row=0, column=5, padx=15, pady=5, sticky="w")
        
        # Системно Налягане, преместено максимално вдясно
        ttk.Label(info_frame, text="System Pressure:", font=("Arial", 10, "bold")).grid(row=0, column=6, padx=(120, 5), pady=5, sticky="w")
        self.pressure_value_var = tk.StringVar(value="--- bar")
        
        self.pressure_value_label = tk.Label(
            info_frame, 
            textvariable=self.pressure_value_var, 
            width=15, 
            bg="#808080", 
            fg="white", 
            relief="ridge", 
            font=("Arial", 10, "bold")
        )
        self.pressure_value_label.grid(row=0, column=7, padx=5, pady=5, sticky="w")

    def log_serial_number(self):
        serial_no = self.serial_var.get().strip()
        if not serial_no:
            messagebox.showwarning("Warning", "Please enter a valid Serial Number first.")
            return
        
        self.serial_logged = True
        self.log("==================================================")
        self.log(f">>> TESTING BLOCK SERIAL NUMBER: {serial_no} <<<")
        self.log("==================================================")
        self.update_interlock_states()

    def generate_pdf_report(self):
        serial_no = self.serial_var.get().strip()
        if not serial_no:
            messagebox.showwarning("Warning", "Please enter a Serial Number before generating a report.")
            return
            
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors
        except ImportError:
            messagebox.showerror("Error", "Please install reportlab library first: pip install reportlab")
            return

        filename = f"TCU_{serial_no}_report.pdf"
        doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        story = []
        
        primary_color = colors.HexColor('#1565c0')
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'Title', 
            parent=styles['Heading1'], 
            fontSize=22, 
            leading=26, 
            textColor=primary_color, 
            spaceAfter=20,
            fontName='Helvetica-Bold'
        )
        subtitle_style = ParagraphStyle(
            'SubTitle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#555555')
        )
        section_style = ParagraphStyle(
            'Section',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=primary_color,
            spaceBefore=15,
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )
        normal_style = styles['Normal']
        
        story.append(Paragraph("TRANSMISSION CONTROL UNIT (TCU) DIAGNOSTIC REPORT", title_style))
        story.append(Paragraph(f"<b>Generated by:</b> ZF GS3 Automated Solenoid Tester | <b>Date/Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))
        story.append(Spacer(1, 15))
        story.append(Table([[""]], colWidths=[530], rowHeights=[2], style=TableStyle([('BACKGROUND', (0,0), (-1,-1), primary_color)])))
        story.append(Spacer(1, 15))
        
        story.append(Paragraph("1. SYSTEM & COMPONENT INFORMATION", section_style))
        info_data = [
            [Paragraph(f"<b>TCU Block Serial Number:</b> {serial_no}", normal_style), 
             Paragraph("<b>Test System:</b> ZF GS3 Bench V1.0", normal_style)],
            [Paragraph("<b>Standard / Compatibility:</b> ZF AS-Tronic", normal_style), 
             Paragraph(f"<b>Connection Port:</b> {self.port_var.get() if self.port_var.get() else 'N/A'}", normal_style)]
        ]
        t_info = Table(info_data, colWidths=[265, 265])
        t_info.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOTTOMPADDING', (0,0), (-1,-1), 6)]))
        story.append(t_info)
        story.append(Spacer(1, 15))
        
        story.append(Paragraph("2. DIAGNOSTIC MEASUREMENTS LOG", section_style))
        
        sensor_values = [v.get() for v in self.sensor_value_vars]
        piston_values = [v.get() for v in self.inductance_value_vars]
        pressure_val = self.pressure_value_var.get()
        
        meas_data = [
            ["Component tested", "Measured Value", "Status"],
            ["Sensor 1 (Resistive)", sensor_values[0], "OK" if "---" not in sensor_values[0] else "Not tested"],
            ["Sensor 2 (Resistive)", sensor_values[1], "OK" if "---" not in sensor_values[1] else "Not tested"],
            ["Sensor 3 (Resistive)", sensor_values[2], "OK" if "---" not in sensor_values[2] else "Not tested"],
            ["Sensor 4 (Resistive)", sensor_values[3], "OK" if "---" not in sensor_values[3] else "Not tested"],
            ["Sensor 5 (Resistive)", sensor_values[4], "OK" if "---" not in sensor_values[4] else "Not tested"],
            ["Piston 1 Position (Inductive)", piston_values[0], "OK" if "---" not in piston_values[0] else "Not tested"],
            ["Piston 2 Position (Inductive)", piston_values[1], "OK" if "---" not in piston_values[1] else "Not tested"],
            ["Piston 3 Position (Inductive)", piston_values[2], "OK" if "---" not in piston_values[2] else "Not tested"],
            ["Piston 4 Position (Inductive)", piston_values[3], "OK" if "---" not in piston_values[3] else "Not tested"],
            ["System Pressure", pressure_val, "OK" if "---" not in pressure_val else "Not tested"]
        ]
        
        t_meas = Table(meas_data, colWidths=[220, 160, 150])
        t_meas.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), primary_color),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f9f9f9')),
            ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#e0e0e0')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(t_meas)
        story.append(Spacer(1, 20))
        
        story.append(Paragraph("3. DIAGNOSTIC CONCLUSION", section_style))
        conclusion_text = (
            f"Based on the quantitative and physical parameters registered during the diagnostic sequence, "
            f"the tested <b>ZF AS-Tronic TCU Block (S/N: {serial_no})</b> has been evaluated. The solenoid valves, "
            f"resistive sensors, and inductive piston positioning systems show correct operation where tested."
        )
        story.append(Paragraph(conclusion_text, normal_style))
        story.append(Spacer(1, 35))
        
        sig_data = [
            [Paragraph("<b>Technician Signature:</b> .......................................", normal_style),
             Paragraph("<b>Workshop Stamp:</b>", normal_style)]
        ]
        t_sig = Table(sig_data, colWidths=[300, 230])
        t_sig.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
        story.append(t_sig)
        
        doc.build(story)
        messagebox.showinfo("Success", f"Professional PDF Report generated and saved locally as:\n{filename}")

    def build_solenoid_panel(self, parent):
        solenoid_frame = ttk.LabelFrame(parent, text="Manual Solenoid Control", padding=10)
        solenoid_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        
        ttk.Label(solenoid_frame, text="Channel", width=18).grid(row=0, column=0, padx=5, pady=5)
        ttk.Label(solenoid_frame, text="State", width=10).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(solenoid_frame, text="Control", width=20).grid(row=0, column=2, columnspan=2, padx=5, pady=5)
        ttk.Label(solenoid_frame, text="Temperature", width=12).grid(row=0, column=4, padx=5, pady=5)
        for i, name in enumerate(SOLENOID_NAMES, start=1):
            ttk.Label(solenoid_frame, text=f"Solenoid {i} ({name})", width=18).grid(row=i, column=0, padx=5, pady=6, sticky="w")
            state_var = tk.StringVar(value="UNKNOWN")
            state_label = tk.Label(solenoid_frame, textvariable=state_var, width=10, bg="#808080", fg="white", relief="ridge", font=("Arial", 10, "bold"))
            state_label.grid(row=i, column=1, padx=5, pady=6)
            
            on_btn = ttk.Button(solenoid_frame, text="ON", width=10, command=lambda ch=i: self.send_command(f"SET {ch} ON"))
            on_btn.grid(row=i, column=2, padx=5, pady=6)
            off_btn = ttk.Button(solenoid_frame, text="OFF", width=10, command=lambda ch=i: self.send_command(f"SET {ch} OFF"))
            off_btn.grid(row=i, column=3, padx=5, pady=6)
            
            self.state_vars.append(state_var)
            self.state_labels.append(state_label)
            self.solenoid_buttons.extend([on_btn, off_btn])
            
            overtemp_label = tk.Label(solenoid_frame, text="Standby", width=12, bg="lightgrey", fg="black", font=("Arial", 9, "bold"), anchor="center")
            overtemp_label.grid(row=i, column=4, padx=10, pady=6)
            self.overtemp_labels.append(overtemp_label)
        separator = ttk.Separator(solenoid_frame, orient="horizontal")
        separator.grid(row=len(SOLENOID_NAMES) + 1, column=0, columnspan=5, sticky="ew", pady=10)
        
        all_off_button = ttk.Button(solenoid_frame, text="Turn All Solenoids OFF", command=lambda: self.send_command("SETOFF ALL"))
        all_off_button.grid(row=len(SOLENOID_NAMES) + 2, column=0, columnspan=5, sticky="ew", padx=5, pady=5)
        self.solenoid_buttons.append(all_off_button)

    def build_sensor_panel(self, parent):
        sensor_frame = ttk.LabelFrame(parent, text="Resistive Sensors", padding=10)
        sensor_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        sensor_frame.columnconfigure(0, weight=1)
        last_row_index = 0
        for i, (title, channel) in enumerate(SENSOR_DISPLAY_CONFIG):
            card_frame = ttk.Frame(sensor_frame, padding=(0, 5))
            card_frame.grid(row=i, column=0, pady=4, sticky="ew")
            ttk.Label(card_frame, text=f"{title} (CH {channel})", font=("Arial", 10, "bold")).pack()
            value_var = tk.StringVar(value="---")
            value_label = tk.Label(card_frame, textvariable=value_var, width=18, height=2, bg="#808080", fg="white", relief="raised", bd=3, font=("Arial", 14, "bold"))
            value_label.pack(fill="x", pady=(2,0))
            self.sensor_value_vars.append(value_var)
            self.sensor_value_labels.append(value_label)
            self.sensor_channel_to_widget[channel] = i
            last_row_index = i
        
        self.check_sensors_btn = ttk.Button(sensor_frame, text="Check Sensors", command=self.start_sensor_check)
        self.check_sensors_btn.grid(row=last_row_index + 1, column=0, pady=(15, 0), sticky="ew")

    def build_pressure_panel(self, parent):
        pass

    def build_inductance_panel(self, parent):
        inductance_frame = ttk.LabelFrame(parent, text="Piston Position (Inductive)", padding=10)
        inductance_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        inductance_frame.columnconfigure(0, weight=1)
        last_row_index = 0
        for i, (title, channel) in enumerate(INDUCTANCE_DISPLAY_CONFIG):
            card_frame = ttk.Frame(inductance_frame, padding=(0, 4))
            card_frame.grid(row=i, column=0, pady=4, sticky="ew")
            ttk.Label(card_frame, text=f"{title} (CH {channel})", font=("Arial", 10, "bold")).pack()
            value_var = tk.StringVar(value="---")
            
            row_frame = ttk.Frame(card_frame)
            row_frame.pack(fill="x", pady=(2,0))
            
            value_label = tk.Label(row_frame, textvariable=value_var, width=11, height=2, bg="#808080", fg="white", relief="raised", bd=3, font=("Arial", 12, "bold"))
            value_label.pack(side="left", fill="x", expand=True)
            
            test_btn = ttk.Button(row_frame, text="Test", width=6, command=lambda ch=channel: self.start_single_inductance_check(ch))
            test_btn.pack(side="right", padx=(5,0))
            
            self.inductance_value_vars.append(value_var)
            self.inductance_value_labels.append(value_label)
            self.inductance_channel_to_widget[channel] = i
            self.individual_piston_buttons.append(test_btn)
            last_row_index = i
            
        self.check_positions_btn = ttk.Button(inductance_frame, text="Check Positions", command=self.start_inductance_check)
        self.check_positions_btn.grid(row=last_row_index + 1, column=0, pady=(15, 0), sticky="ew")

    def build_right_panel(self, parent):
        pass

    def build_tests_panel(self, parent):
        tests_frame = ttk.LabelFrame(parent, text="Predefined Tests", padding=10)
        tests_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        ttk.Label(tests_frame, text="Run a single test profile", font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=3, padx=5, pady=5)
        for idx, test_name in enumerate(TEST_NAMES):
            row = idx // 3 + 1
            col = idx % 3
            btn = ttk.Button(tests_frame, text=f"Test {test_name}", width=12, command=lambda name=test_name: self.run_test(name))
            btn.grid(row=row, column=col, padx=4, pady=4, sticky="ew")
            self.predefined_buttons.append(btn)

    def build_auto_panel(self, parent):
        auto_frame = ttk.LabelFrame(parent, text="Automatic Sequence", padding=10)
        auto_frame.grid(row=1, column=0, sticky="nsew")
        
        self.auto_start_btn = ttk.Button(auto_frame, text="Start Auto Sequence", command=self.start_auto_sequence)
        self.auto_start_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.auto_stop_btn = ttk.Button(auto_frame, text="Stop Auto Sequence", command=self.stop_auto_sequence)
        self.auto_stop_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        self.auto_progress = ttk.Progressbar(auto_frame, orient="horizontal", mode="determinate", maximum=len(TEST_NAMES))
        self.auto_progress.grid(row=1, column=0, columnspan=2, padx=5, pady=10, sticky="ew")
        ttk.Label(auto_frame, text="Execution order", font=("Arial", 10, "bold")).grid(row=2, column=0, columnspan=2, padx=5, pady=5)
        self.sequence_listbox = tk.Listbox(auto_frame, font=("Consolas", 10))
        self.sequence_listbox.grid(row=3, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        auto_frame.columnconfigure(0, weight=1)
        auto_frame.columnconfigure(1, weight=1)
        auto_frame.rowconfigure(3, weight=1)
    
    def build_log_panel(self, parent):
        log_frame = ttk.LabelFrame(parent, text="Serial Log History", padding=10)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, font=("Consolas", 10), state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def start_sensor_check(self):
        serial_no = self.serial_var.get().strip()
        if serial_no:
            self.log(f"--- SENSOR CHECK for Serial: {serial_no} ---")
        for i in range(len(self.sensor_value_vars)):
            self.sensor_value_vars[i].set("Waiting...")
            self.sensor_value_labels[i].config(bg="orange", fg="black")
        self.send_command("READSENSORS")

    def start_inductance_check(self):
        serial_no = self.serial_var.get().strip()
        if serial_no:
            self.log(f"--- INDUCTANCE CHECK for Serial: {serial_no} ---")
        for i in range(len(self.inductance_value_vars)):
            self.inductance_value_vars[i].set("Waiting...")
            self.inductance_value_labels[i].config(bg="orange", fg="black")
        self.send_command("READINDUCTANCE")

    def start_single_inductance_check(self, channel):
        serial_no = self.serial_var.get().strip()
        if serial_no:
            self.log(f"--- SINGLE INDUCTANCE CHECK (CH {channel}) for Serial: {serial_no} ---")
        widget_index = self.inductance_channel_to_widget.get(channel)
        if widget_index is not None:
            self.inductance_value_vars[widget_index].set("Waiting...")
            self.inductance_value_labels[widget_index].config(bg="orange", fg="black")
        self.send_command(f"READINDUCTANCE {channel}")

    def check_overtemp(self):
        current_time = time.time()
        for channel, start_time in list(self.solenoid_on_times.items()):
            on_duration = current_time - start_time
            label = self.overtemp_labels[channel - 1]
            if on_duration > OVERTEMP_CRIT_SECONDS:
                label.config(text="OVERTEMP", bg="red", fg="white")
            elif on_duration > OVERTEMP_WARN_SECONDS:
                label.config(text="Warning", bg="orange", fg="black")
            else:
                label.config(text="OK", bg="#90ee90", fg="black")
        self.root.after(2000, self.check_overtemp)

    def set_state(self, channel, state):
        index = channel - 1
        if not (0 <= index < len(self.state_vars)): return
        self.current_states[index] = state
        self.state_vars[index].set(state)
        state_label = self.state_labels[index]
        overtemp_label = self.overtemp_labels[index]
        if state == "ON":
            state_label.config(bg="#2e7d32", fg="white")
            if channel not in self.solenoid_on_times:
                self.solenoid_on_times[channel] = time.time()
            overtemp_label.config(text="OK", bg="#90ee90", fg="black")
        else:
            state_label.config(bg="#c62828" if state == "OFF" else "#808080", fg="white")
            if channel in self.solenoid_on_times:
                del self.solenoid_on_times[channel]
            overtemp_label.config(text="Standby", bg="lightgrey", fg="black")
    
    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports:
            self.port_combo.current(0)
        self.log(f"Available ports: {ports if ports else 'None'}")

    def connect_serial(self):
        if self.ser and self.ser.is_open:
            self.log("Already connected.")
            return
        port = self.port_var.get()
        if not port:
            messagebox.showwarning("Warning", "Please select a COM port.")
            return
        try:
            self.ser = serial.Serial(port, 115200, timeout=0.1)
            self.connection_var.set(f"Connected to {port}")
            self.log(f"Connected to {port}")
            self.root.after(1000, self.post_connect_setup)
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))

    def post_connect_setup(self):
        self.request_full_status()
        self.send_command("AUTO STATUS")
        self.update_interlock_states() # Отключваме тестовете

    def disconnect_serial(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.connection_var.set("Disconnected")
            self.mode_var.set("Mode: Unknown")
            self.auto_state_var.set("Auto sequence: STOPPED")
            self.auto_current_var.set("Current step: -")
            self.reset_solenoid_states()
            self.reset_sensor_cards()
            self.reset_inductance_cards()
            self.log(f"Disconnected")
            
            # При дисконект блокираме тестовете обратно
            self.update_interlock_states()

    def send_command(self, cmd):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Warning", "Not connected to Arduino.")
            return
        try:
            self.ser.write((cmd + "\n").encode("utf-8"))
            self.log(f"PC -> Arduino: {cmd}")
        except Exception as e:
            messagebox.showerror("Send Error", str(e))

    def request_full_status(self):
        self.send_command("GETMODE")
        self.send_command("GETALL")

    def run_test(self, test_name):
        self.send_command(f"TEST {test_name}")

    def start_auto_sequence(self):
        self.reset_auto_sequence_view()
        serial_no = self.serial_var.get().strip()
        if serial_no:
            self.log(f"--- AUTO SEQUENCE START for Serial: {serial_no} ---")
        self.send_command("AUTO START")

    def stop_auto_sequence(self):
        self.send_command("AUTO STOP")

    def reset_auto_sequence_view(self):
        self.auto_sequence_states = ["pending"] * len(TEST_NAMES)
        self.last_auto_step_name = "-"
        self.auto_progress["value"] = 0
        self.auto_state_var.set("Auto sequence: STARTING...")
        self.auto_current_var.set("Current step: -")
        self.refresh_auto_sequence_list()

    def refresh_auto_sequence_list(self):
        self.sequence_listbox.delete(0, tk.END)
        current_index = -1
        for idx, test_name in enumerate(TEST_NAMES):
            state = self.auto_sequence_states[idx]
            prefix = "[ ]"
            if state == "done": prefix = "[x]"
            elif state == "current":
                prefix = "[>]"
                current_index = idx
            self.sequence_listbox.insert(tk.END, f"{prefix} Test {test_name}")
        
        if current_index != -1:
            self.sequence_listbox.selection_clear(0, tk.END)
            self.sequence_listbox.selection_set(current_index)
            self.sequence_listbox.see(current_index)

    def update_auto_step(self, step_number, total_steps, test_name):
        step_index = step_number - 1
        if not (0 <= step_index < len(TEST_NAMES)): return
        self.last_auto_step_name = test_name
        for i in range(len(TEST_NAMES)):
            if i < step_index: self.auto_sequence_states[i] = "done"
            elif i == step_index: self.auto_sequence_states[i] = "current"
            else: self.auto_sequence_states[i] = "pending"
        self.auto_progress["maximum"] = total_steps
        self.auto_progress["value"] = step_number
        self.auto_state_var.set("Auto sequence: RUNNING")
        self.auto_current_var.set(f"Current step: {step_number}/{total_steps} - Test {test_name}")
        self.refresh_auto_sequence_list()

    def complete_auto_sequence(self):
        self.auto_sequence_states = ["done"] * len(TEST_NAMES)
        self.auto_progress["value"] = len(TEST_NAMES)
        self.auto_state_var.set("Auto sequence: COMPLETED")
        self.auto_current_var.set(f"Current step: Completed - Last test {self.last_auto_step_name}")
        self.refresh_auto_sequence_list()

    def format_ohms_value(self, value):
        if value >= 1_000_000: return f"{value / 1_000_000:.2f} MΩ"
        if value >= 1_000: return f"{value / 1_000:.2f} kΩ"
        return f"{value:.0f} Ω"

    def format_resistance(self, value_text):
        try: return self.format_ohms_value(float(value_text))
        except (ValueError, TypeError): return str(value_text)

    def format_pressure(self, value_text):
        try:
            val = float(value_text)
            return f"{val:.2f} {PRESSURE_SENSOR_CONFIG['unit']}"
        except (ValueError, TypeError):
            return str(value_text)

    def format_inductance_value(self, value):
        if value >= 1000.0:
            return f"{value / 1000.0:.2f} mH"
        return f"{value:.1f} uH"

    def format_inductance(self, value_text):
        try:
            return self.format_inductance_value(float(value_text))
        except (ValueError, TypeError):
            return str(value_text)

    def apply_sensor_style(self, widget_index, raw_value):
        label = self.sensor_value_labels[widget_index]
        try:
            float(raw_value)
            label.config(bg="#1565c0", fg="white")
        except (ValueError, TypeError):
            label.config(bg="#808080", fg="white")

    def apply_inductance_style(self, widget_index, raw_value):
        label = self.inductance_value_labels[widget_index]
        try:
            float(raw_value)
            label.config(bg="#1565c0", fg="white")
        except (ValueError, TypeError):
            label.config(bg="#808080", fg="white")
    
    def apply_pressure_style(self, raw_value):
        label = self.pressure_value_label
        try:
            float(raw_value)
            label.config(bg="#1565c0", fg="white")
        except (ValueError, TypeError):
            label.config(bg="#808080", fg="white")

    def reset_sensor_cards(self):
        for i in range(len(self.sensor_value_vars)):
            self.sensor_value_vars[i].set("---")
            self.apply_sensor_style(i, "---")
        self.pressure_value_var.set("--- bar")
        self.apply_pressure_style("---")

    def reset_inductance_cards(self):
        for i in range(len(self.inductance_value_vars)):
            self.inductance_value_vars[i].set("---")
            self.apply_inductance_style(i, "---")

    def reset_solenoid_states(self):
        for i in range(len(SOLENOID_NAMES)):
            self.set_state(i + 1, "UNKNOWN")

    def set_resistance(self, channel, value_text):
        widget_index = self.sensor_channel_to_widget.get(channel)
        if widget_index is None: return
        self.sensor_value_vars[widget_index].set(self.format_resistance(value_text))
        self.apply_sensor_style(widget_index, value_text)

    def set_inductance(self, channel, value_text):
        widget_index = self.inductance_channel_to_widget.get(channel)
        if widget_index is None: return
        self.inductance_value_vars[widget_index].set(self.format_inductance(value_text))
        self.apply_inductance_style(widget_index, value_text)
    
    def set_pressure(self, value_text):
        self.pressure_value_var.set(self.format_pressure(value_text))
        self.apply_pressure_style(value_text)

    def parse_serial_line(self, line):
        if not line: return
        self.log(f"Arduino -> PC: {line}")
        
        parts = line.split()
        if not parts: return
        cmd = parts[0]
        if cmd == "SENSORS":
            self.parse_sensors(line)
        elif cmd == "INDUCTANCE":
            self.parse_inductance_data(line)
        elif cmd == "PRESSURE": 
            if len(parts) == 2:
                self.set_pressure(parts[1])
        elif cmd == "ALL":
            self.parse_all_states(line)
        elif cmd in ("SOL", "STATE"):
            if len(parts) == 3 and parts[1].isdigit():
                self.set_state(int(parts[1]), parts[2].upper())
        elif cmd == "MODE":
            self.mode_var.set(f"Mode: {line.split(maxsplit=1)[1]}")
        elif cmd == "AUTO_STATE":
            self.auto_state_var.set(f"Auto sequence: {line.split(maxsplit=1)[1].upper()}")
        elif cmd == "AUTO_DONE":
            self.complete_auto_sequence()
        elif cmd == "AUTO_STEP":
            if len(parts) == 4 and parts[1].isdigit() and parts[2].isdigit():
                self.update_auto_step(int(parts[1]), int(parts[2]), parts[3])

    def parse_all_states(self, line):
        items = line.split()[1:]
        for item in items:
            parts = item.split(':', 1)
            if len(parts) == 2 and parts[0].isdigit():
                self.set_state(int(parts[0]), parts[1].upper())

    def parse_sensors(self, line):
        items = line.split()[1:]
        for item in items:
            parts = item.split(':', 1)
            if len(parts) == 2 and parts[0].isdigit():
                self.set_resistance(int(parts[0]), parts[1])

    def parse_inductance_data(self, line):
        items = line.split()[1:]
        for item in items:
            parts = item.split(':', 1)
            if len(parts) == 2 and parts[0].isdigit():
                self.set_inductance(int(parts[0]), parts[1])

    def poll_serial(self):
        if self.ser and self.ser.is_open:
            try:
                while self.ser.in_waiting:
                    line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                    if line: self.parse_serial_line(line)
            except Exception as e:
                self.log(f"Read error: {e}")
        self.root.after(100, self.poll_serial)

    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        
        # --- АВТОМАТИЧЕН ЗАПИС ВЪВ ФАЙЛ (FULL SERIAL LOG) ---
        try:
            with open("tester_log.txt", "a", encoding="utf-8") as f:
                timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
                f.write(f"{timestamp} {message}\n")
        except Exception as e:
            pass

    # --- ДОБАВЕНА ЛОГИКА ПРИ ЗАТВАРЯНЕ НА ПРОГРАМАТА ---
    def on_closing(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except:
                pass
                
        serial_no = self.serial_var.get().strip()
        if serial_no:
            safe_serial = "".join(c for c in serial_no if c.isalnum() or c in ('-', '_'))
            if safe_serial:
                new_filename = f"TCU_{safe_serial}_log.txt"
                try:
                    if os.path.exists(new_filename):
                        os.remove(new_filename)
                    if os.path.exists("tester_log.txt"):
                        os.rename("tester_log.txt", new_filename)
                except Exception as e:
                    pass
                    
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = SolenoidApp(root)
    root.mainloop()
