import tkinter as tk
from tkinter import messagebox, ttk
import customtkinter as ctk 
import serial
import serial.tools.list_ports
import time
import os

#test
# --- Настройки на CustomTkinter ---
ctk.set_appearance_mode("Dark")     # Тъмен режим
ctk.set_default_color_theme("blue")  # Синя тема на бутоните

# --- Палитра от Матови/Пастелни Цветове ---
BG_SOLID = "#18181a"           # Плътен графитен фон за абсолютно всичко
MATTE_GREEN = "#3b5e40"        # Пастелно горско зелено
MATTE_GREEN_HOVER = "#2a452e"  
MATTE_RED = "#8c3a3a"          # Матово тухлено червено
MATTE_RED_HOVER = "#692b2b"    
MATTE_BLUE = "#3a5c7c"         # Матово стоманено синьо (Slate Blue)
MATTE_BLUE_HOVER = "#27415e"   
MATTE_GRAY = "#3a3a3a"         # Неутрално матово сиво за Standby

# --- Constants ---
SOLENOID_NAMES = ["Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9", "Y1", "Y10"]
TEST_NAMES = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "RL", "RH"]
SENSOR_DISPLAY_CONFIG = [("Sensor 1", 1), ("Sensor 2", 2), ("Sensor 3", 3), ("Sensor 4", 4), ("Sensor 5", 5)]
PRESSURE_SENSOR_CONFIG = {"title": "System Pressure", "unit": "bar"}

# Конфигурация за буталата и техните аналогови скали с две зелени граници (за прибрано/IN и избутано/OUT положение)
# Можете лесно да променяте тези граници според реалните данни по-късно!
INDUCTANCE_DISPLAY_CONFIG = [
    # (Заглавие, Канал, Мин скала, Зелена зона 1 Мин, Зелена зона 1 Макс, Зелена зона 2 Мин, Зелена зона 2 Макс, Макс скала)
    ("Piston 1", 1, 500, 800, 1200, 1800, 2200, 2500),
    ("Piston 2", 2, 500, 800, 1200, 1800, 2200, 2500),
    ("Piston 3", 3, 500, 800, 1200, 1800, 2200, 2500),
    ("Piston 4", 4, 500, 800, 1200, 1800, 2200, 2500)
]

OVERTEMP_WARN_SECONDS = 60
OVERTEMP_CRIT_SECONDS = 120

class SolenoidApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ZF GS3 Solenoid Tester")
        self.root.geometry("1800x850")
        self.root.minsize(1300, 700)
        
        # Настройка на цвета на самия прозорец за плътен фон
        self.root.configure(fg_color=BG_SOLID)
        
        # Свързваме затварянето на прозореца с нашата функция
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Основен контейнер на CustomTkinter с плътен фон
        app_frame = ctk.CTkFrame(root, corner_radius=0, fg_color=BG_SOLID)
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
        self.piston_canvases = [] # Списък за пазители на скалите за индуктивност
        
        self.current_states = ["UNKNOWN"] * len(SOLENOID_NAMES)
        self.auto_sequence_states = ["pending"] * len(TEST_NAMES)
        self.last_auto_step_name = "-"
        
        self.overtemp_labels = []
        self.solenoid_on_times = {}
        
        # Списъци за блокировка на бутоните
        self.solenoid_buttons = []
        self.predefined_buttons = []
        self.individual_piston_buttons = []  # Ще пази бутоните за MAX IN / MAX OUT
        self.serial_logged = False # Блокировката е активна по подразбиране
        
        # --- ИЗТРИВАНЕ НА СТАРИЯ ЛОГ И СТАРТИРАНЕ НА НОВА СЕСИЯ ---
        try:
            with open("tester_log.txt", "w", encoding="utf-8") as f:
                f.write(f"=== TEST SESSION STARTED AT {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception as e:
            pass
        
        # --- СТРАНИЧНА НАВИГАЦИОННА СТРУКТУРА (SIDEBAR ОТ ДОЛУ ДО ГОРЕ) ---
        # Ляв панел за менюто (Sidebar)
        self.sidebar_frame = ctk.CTkFrame(
            app_frame, 
            width=220, 
            corner_radius=0,         # Без ъгли отляво за перфектно прилепване
            fg_color=BG_SOLID,       # Плътен цвят
            border_width=1,          # Фина 1px рамка
            border_color="#333333"   # Матов цвят за рамката
        )
        self.sidebar_frame.pack(side="left", fill="y")
        self.sidebar_frame.pack_propagate(False) # Фиксиран размер на менюто
        
        # Заглавие/Лого на сайдбара
        ctk.CTkLabel(self.sidebar_frame, text="ZF GS3", font=("Arial", 22, "bold"), text_color=MATTE_BLUE).pack(pady=20)
        
        # Бутони в страничното меню
        self.btn_solenoids = ctk.CTkButton(self.sidebar_frame, text=" 🔌 Solenoids & Tests", height=45, anchor="w", fg_color="transparent", text_color="white", hover_color="#2b2b2b", command=lambda: self.show_page("solenoids"))
        self.btn_solenoids.pack(fill="x", padx=10, pady=5)
        
        self.btn_sensors = ctk.CTkButton(self.sidebar_frame, text=" 📊 Sensors & Position", height=45, anchor="w", fg_color="transparent", text_color="white", hover_color="#2b2b2b", command=lambda: self.show_page("sensors"))
        self.btn_sensors.pack(fill="x", padx=10, pady=5)
        
        self.btn_logs = ctk.CTkButton(self.sidebar_frame, text=" 📝 Serial Log History", height=45, anchor="w", fg_color="transparent", text_color="white", hover_color="#2b2b2b", command=lambda: self.show_page("logs"))
        self.btn_logs.pack(fill="x", padx=10, pady=5)
        
        # Дясна работна зона (поема всичко останало) - Плътен цвят
        self.right_area = ctk.CTkFrame(app_frame, fg_color=BG_SOLID, corner_radius=0)
        self.right_area.pack(side="left", fill="both", expand=True, padx=10, pady=5)
        
        # 1. Горният панел за връзка отива най-горе в ДЯСНАТА зона
        self.build_top_panel(self.right_area)
        
        # 2. Десен контейнер за страниците (в средата)
        self.content_frame = ctk.CTkFrame(self.right_area, fg_color=BG_SOLID, corner_radius=0)
        self.content_frame.pack(fill="both", expand=True, pady=5)
        
        # Създаваме физическите страници (Frames)
        self.page_solenoids = ctk.CTkFrame(self.content_frame, fg_color=BG_SOLID, corner_radius=0)
        self.page_sensors = ctk.CTkFrame(self.content_frame, fg_color=BG_SOLID, corner_radius=0)
        self.page_logs = ctk.CTkFrame(self.content_frame, fg_color=BG_SOLID, corner_radius=0)
        
        # Изграждаме съдържанието за всяка от страниците
        # --- Страница 1: Соленоиди ---
        self.page_solenoids.rowconfigure(0, weight=1)
        self.page_solenoids.columnconfigure(0, weight=2)
        self.page_solenoids.columnconfigure(1, weight=1)
        
        self.build_solenoid_panel(self.page_solenoids)
        
        right_sol_frame = ctk.CTkFrame(self.page_solenoids, fg_color="transparent")
        right_sol_frame.grid(row=0, column=1, sticky="nsew", padx=(15, 0))
        right_sol_frame.rowconfigure(1, weight=1)
        right_sol_frame.columnconfigure(0, weight=1)
        
        self.build_tests_panel(right_sol_frame)
        self.build_auto_panel(right_sol_frame)
        
        # --- Страница 2: Сензори ---
        self.page_sensors.rowconfigure(0, weight=1)
        self.page_sensors.columnconfigure(0, weight=1)
        self.page_sensors.columnconfigure(1, weight=1)
        
        self.build_sensor_panel(self.page_sensors)
        self.build_inductance_panel(self.page_sensors)
        
        # --- Страница 3: Логове ---
        self.build_log_panel(self.page_logs)
        
        # 3. Модерният Статус панел отива най-долу в ДЯСНАТА зона
        self.build_info_panel(self.right_area)
        
        self.refresh_ports()
        self.refresh_auto_sequence_list()
        self.reset_sensor_cards()
        self.reset_inductance_cards()
        self.poll_serial()
        self.check_overtemp()
        
        # По подразбиране показваме първата страница
        self.show_page("solenoids")
        
        # Прилагаме блокировката
        self.update_interlock_states()

    def show_page(self, page_name):
        # Скриваме всички страници мигновено (без анимации)
        self.page_solenoids.pack_forget()
        self.page_sensors.pack_forget()
        self.page_logs.pack_forget()
        
        # Нулираме цветовете на бутоните в сайдбара
        self.btn_solenoids.configure(fg_color="transparent")
        self.btn_sensors.configure(fg_color="transparent")
        self.btn_logs.configure(fg_color="transparent")
        
        # Показваме избраната страница и активираме съответния бутон
        if page_name == "solenoids":
            self.page_solenoids.pack(fill="both", expand=True)
            self.btn_solenoids.configure(fg_color=MATTE_BLUE)
        elif page_name == "sensors":
            self.page_sensors.pack(fill="both", expand=True)
            self.btn_sensors.configure(fg_color=MATTE_BLUE)
        elif page_name == "logs":
            self.page_logs.pack(fill="both", expand=True)
            self.btn_logs.configure(fg_color=MATTE_BLUE)

    def update_interlock_states(self):
        conn_state = "normal" if self.serial_logged else "disabled"
        self.port_combo.configure(state="readonly" if self.serial_logged else "disabled")
        if hasattr(self, 'refresh_ports_btn'): self.refresh_ports_btn.configure(state=conn_state)
        if hasattr(self, 'connect_btn'): self.connect_btn.configure(state=conn_state)
        if hasattr(self, 'disconnect_btn'): self.disconnect_btn.configure(state=conn_state)
        
        is_connected = self.ser is not None and self.ser.is_open
        test_state = "normal" if (self.serial_logged and is_connected) else "disabled"
        
        # Блокировка на бутони за соленоиди
        for btn in self.solenoid_buttons:
            btn.configure(state=test_state)
            
        # Блокировка на предефинирани тестове
        for btn in self.predefined_buttons:
            btn.configure(state=test_state)
            
        # Блокировка на авто поредица
        if hasattr(self, 'auto_start_btn'): self.auto_start_btn.configure(state=test_state)
        if hasattr(self, 'auto_stop_btn'): self.auto_stop_btn.configure(state=test_state)
        
        # Блокировка на сензори и позиции
        if hasattr(self, 'check_sensors_btn'): self.check_sensors_btn.configure(state=test_state)
        if hasattr(self, 'check_positions_btn'): self.check_positions_btn.configure(state=test_state)
        
        # Блокировка на индивидуални бутони за буталата (MAX IN / MAX OUT)
        for btn in self.individual_piston_buttons:
            btn.configure(state=test_state)
            
        # Блокировка на PDF бутона
        if hasattr(self, 'pdf_report_btn'): self.pdf_report_btn.configure(state="normal" if self.serial_logged else "disabled")

    def build_top_panel(self, parent):
        top_frame = ctk.CTkFrame(
            parent, 
            corner_radius=10, 
            fg_color="#18181a",
            border_width=1,
            border_color="#333333"
        )
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

    def build_info_panel(self, parent):
        info_frame = ctk.CTkFrame(
            parent, 
            corner_radius=10,
            fg_color="#18181a",
            border_width=1,
            border_color="#333333"
        )
        info_frame.pack(fill="x", padx=10, pady=5)
        
        self.connection_var = tk.StringVar(value="Not connected")
        self.mode_var = tk.StringVar(value="Mode: Unknown")
        self.auto_state_var = tk.StringVar(value="Auto sequence: STOPPED")
        self.auto_current_var = tk.StringVar(value="Current step: -")
        
        ctk.CTkLabel(info_frame, textvariable=self.connection_var, font=("Arial", 11)).grid(row=0, column=0, padx=15, pady=8, sticky="w")
        ctk.CTkLabel(info_frame, textvariable=self.mode_var, font=("Arial", 11, "bold")).grid(row=0, column=1, padx=20, pady=8, sticky="w")
        
        # Сериен Номер и PDF
        ctk.CTkLabel(info_frame, text="Block Serial No:", font=("Arial", 11, "bold")).grid(row=0, column=2, padx=(40, 5), pady=8, sticky="w")
        self.serial_var = tk.StringVar(value="")
        self.serial_entry = ctk.CTkEntry(info_frame, textvariable=self.serial_var, width=150, font=("Consolas", 11, "bold"))
        self.serial_entry.grid(row=0, column=3, padx=5, pady=8, sticky="w")
        
        self.log_serial_btn = ctk.CTkButton(info_frame, text="Log Serial", width=100, command=self.log_serial_number)
        self.log_serial_btn.grid(row=0, column=4, padx=5, pady=8, sticky="w")
        
        self.pdf_report_btn = ctk.CTkButton(info_frame, text="PDF Report", width=100, fg_color=MATTE_BLUE, hover_color=MATTE_BLUE_HOVER, command=self.generate_pdf_report)
        self.pdf_report_btn.grid(row=0, column=5, padx=15, pady=8, sticky="w")
        
        # Системно Налягане, преместено максимално вдясно
        ctk.CTkLabel(info_frame, text="System Pressure:", font=("Arial", 11, "bold")).grid(row=0, column=6, padx=(120, 5), pady=8, sticky="w")
        self.pressure_value_var = tk.StringVar(value="--- bar")
        
        self.pressure_value_label = ctk.CTkLabel(
            info_frame, 
            textvariable=self.pressure_value_var, 
            width=100, 
            height=28,
            fg_color="#333333", 
            text_color="white", 
            corner_radius=6, 
            font=("Arial", 11, "bold")
        )
        self.pressure_value_label.grid(row=0, column=7, padx=15, pady=8, sticky="w")

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
            f"the tested TCU Block S/N {serial_no} has been evaluated."
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
        messagebox.showinfo("Success", f"Professional PDF Report generated and saved locally as {filename}")

    def build_solenoid_panel(self, parent):
        solenoid_frame = ctk.CTkFrame(parent, corner_radius=10)
        solenoid_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        
        ctk.CTkLabel(solenoid_frame, text="Channel", font=("Arial", 11, "bold")).grid(row=0, column=0, padx=5, pady=5)
        ctk.CTkLabel(solenoid_frame, text="State", font=("Arial", 11, "bold")).grid(row=0, column=1, padx=5, pady=5)
        ctk.CTkLabel(solenoid_frame, text="Control", font=("Arial", 11, "bold")).grid(row=0, column=2, columnspan=2, padx=5, pady=5)
        ctk.CTkLabel(solenoid_frame, text="Temperature", font=("Arial", 11, "bold")).grid(row=0, column=4, padx=5, pady=5)
        for i, name in enumerate(SOLENOID_NAMES, start=1):
            ctk.CTkLabel(solenoid_frame, text=f"Solenoid {i} ({name})", anchor="w").grid(row=i, column=0, padx=10, pady=6, sticky="w")
            state_var = tk.StringVar(value="UNKNOWN")
            
            state_label = ctk.CTkLabel(
                solenoid_frame, 
                textvariable=state_var, 
                width=80, 
                height=26,
                fg_color="#444444", 
                text_color="white", 
                corner_radius=6, 
                font=("Arial", 10, "bold")
            )
            state_label.grid(row=i, column=1, padx=5, pady=6)
            
            on_btn = ctk.CTkButton(solenoid_frame, text="ON", width=70, height=26, fg_color=MATTE_GREEN, hover_color=MATTE_GREEN_HOVER, command=lambda ch=i: self.send_command(f"SET {ch} ON"))
            on_btn.grid(row=i, column=2, padx=5, pady=6)
            off_btn = ctk.CTkButton(solenoid_frame, text="OFF", width=70, height=26, fg_color=MATTE_RED, hover_color=MATTE_RED_HOVER, command=lambda ch=i: self.send_command(f"SET {ch} OFF"))
            off_btn.grid(row=i, column=3, padx=5, pady=6)
            
            self.state_vars.append(state_var)
            self.state_labels.append(state_label)
            self.solenoid_buttons.extend([on_btn, off_btn])
            
            overtemp_label = ctk.CTkLabel(
                solenoid_frame, 
                text="Standby", 
                width=90, 
                height=26,
                fg_color=MATTE_GRAY, 
                text_color="white", 
                corner_radius=6, 
                font=("Arial", 9, "bold")
            )
            overtemp_label.grid(row=i, column=4, padx=10, pady=6)
            self.overtemp_labels.append(overtemp_label)
            
        separator = ttk.Separator(solenoid_frame, orient="horizontal")
        separator.grid(row=len(SOLENOID_NAMES) + 1, column=0, columnspan=5, sticky="ew", pady=10)
        
        all_off_button = ctk.CTkButton(solenoid_frame, text="Turn All Solenoids OFF", fg_color=MATTE_RED, hover_color=MATTE_RED_HOVER, command=lambda: self.send_command("SETOFF ALL"))
        all_off_button.grid(row=len(SOLENOID_NAMES) + 2, column=0, columnspan=5, sticky="ew", padx=10, pady=5)
        self.solenoid_buttons.append(all_off_button)

    def build_sensor_panel(self, parent):
        sensor_frame = ctk.CTkFrame(parent, corner_radius=10)
        sensor_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        sensor_frame.columnconfigure(0, weight=1)
        
        self.sensor_canvases = [] # Списък за пазители на скалите
        
        last_row_index = 0
        for i, (title, channel) in enumerate(SENSOR_DISPLAY_CONFIG):
            card_frame = ctk.CTkFrame(sensor_frame, fg_color="#2b2b2b", corner_radius=8)
            card_frame.grid(row=i, column=0, pady=5, padx=10, sticky="ew")
            
            # Заглавието е най-горе, центрирано
            ctk.CTkLabel(card_frame, text=f"{title} (CH {channel})", font=("Arial", 11, "bold")).pack(pady=(4, 2))
            
            # Хоризонтален под-контейнер за стойността и скалата side-by-side
            row_frame = ctk.CTkFrame(card_frame, fg_color="transparent")
            row_frame.pack(fill="x", padx=10, pady=(0, 6))
            
            value_var = tk.StringVar(value="---")
            
            # Ляво: Стойността на сензора
            value_label = ctk.CTkLabel(
                row_frame, 
                textvariable=value_var, 
                width=110, 
                height=35,
                fg_color="#444444", 
                text_color="white", 
                corner_radius=6, 
                font=("Arial", 12, "bold")
            )
            value_label.pack(side="left", padx=(0, 10))
            
            # Дясно: Визуалната аналогова скала (ОГРОМНА И МАКСИМАЛНО ДЕТАЙЛНА)
            canvas = tk.Canvas(row_frame, width=450, height=34, bg="#2b2b2b", highlightthickness=0)
            canvas.pack(side="right", fill="x", expand=True)
            self.sensor_canvases.append(canvas)
            
            self.sensor_value_vars.append(value_var)
            self.sensor_value_labels.append(value_label)
            self.sensor_channel_to_widget[channel] = i
            last_row_index = i
            
            # Начертаваме празната скала при зареждане
            self.draw_sensor_gauge(i, "---")
        
        # ОПТИМИЗАЦИЯ: Бутонът "Check Sensors" вече не разтяга прозореца излишно
        self.check_sensors_btn = ctk.CTkButton(sensor_frame, text="Check Sensors", height=35, width=180, command=self.start_sensor_check)
        self.check_sensors_btn.grid(row=last_row_index + 1, column=0, pady=(15, 0), padx=10)

    # ЧЕРТАНЕ НА НОВАТА СУПЕР ГОЛЯМА АНАЛОГОВА СКАЛА ОТДЯСНО (450px)
    def draw_sensor_gauge(self, index, value_text):
        canvas = self.sensor_canvases[index]
        canvas.delete("all")
        
        # Нарисувай сивата фонова лента (скала от 50 до 90 ома, ширина 420px с 15px офсет отляво)
        canvas.create_rectangle(15, 8, 435, 18, fill="#444444", outline="")
        
        # Нарисувай "зелената зона" (допустими граници 65 - 75 ома)
        # 65 ома е при х=172px, 75 ома е при х=277px
        canvas.create_rectangle(172, 8, 277, 18, fill=MATTE_GREEN, outline="")
        
        # Големи и контрастни текстови означения за границите и деленията
        canvas.create_text(15, 28, text="50", fill="#666666", font=("Arial", 9))
        canvas.create_text(172, 28, text="65", fill="#888888", font=("Arial", 9, "bold"))
        canvas.create_text(277, 28, text="75", fill="#888888", font=("Arial", 9, "bold"))
        canvas.create_text(435, 28, text="90", fill="#666666", font=("Arial", 9))
        
        try:
            clean_text = value_text.replace("Ω", "").replace("kΩ", "").replace("MΩ", "").strip()
            val = float(clean_text)
            
            display_val = val
            if display_val < 50: display_val = 50
            if display_val > 90: display_val = 90
            
            # Изчисляваме пикселната позиция на стрелката (скала 420px)
            x = 15 + ((display_val - 50) / 40.0) * 420
            
            # Нарисувай стрелката (линия и триъгълник)
            canvas.create_line(x, 0, x, 19, fill="white", width=2)
            canvas.create_polygon(x-4, 0, x+4, 0, x, 5, fill="white")
        except:
            pass

    def build_pressure_panel(self, parent):
        pass

    def build_inductance_panel(self, parent):
        inductance_frame = ctk.CTkFrame(parent, corner_radius=10)
        inductance_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        inductance_frame.columnconfigure(0, weight=1)
        last_row_index = 0
        
        for i, config in enumerate(INDUCTANCE_DISPLAY_CONFIG):
            title, channel, min_val, in_start, in_end, out_start, out_end, max_val = config
            
            card_frame = ctk.CTkFrame(inductance_frame, fg_color="#2b2b2b", corner_radius=8)
            card_frame.grid(row=i, column=0, pady=5, padx=10, sticky="ew")
            
            # 1. Заглавие на Piston
            ctk.CTkLabel(card_frame, text=f"{title} (CH {channel})", font=("Arial", 11, "bold")).pack(pady=(4, 2))
            
            # 2. Хоризонтален контейнер за Стойност и ОГРОМНАТА Аналогова скала с две зелени граници
            row_frame = ctk.CTkFrame(card_frame, fg_color="transparent")
            row_frame.pack(fill="x", padx=10, pady=(0, 6))
            
            value_var = tk.StringVar(value="---")
            
            # Текуща стойност на индуктивността
            value_label = ctk.CTkLabel(
                row_frame, 
                textvariable=value_var, 
                width=110, 
                height=35,
                fg_color="#444444", 
                text_color="white", 
                corner_radius=6, 
                font=("Arial", 12, "bold")
            )
            value_label.pack(side="left", padx=(0, 10))
            
            # Новата голяма Аналогова скала за буталата с ДВЕ зелени зони (за прибрано и разгънато състояние)
            canvas = tk.Canvas(row_frame, width=450, height=34, bg="#2b2b2b", highlightthickness=0)
            canvas.pack(side="right", fill="x", expand=True)
            self.piston_canvases.append(canvas)
            
            # 3. Контролни Бутони - MAX OUT и MAX IN (Един до друг за спестяване на място)
            # Сега тези бутони автоматично задействат и измерването на индуктивността след преместването!
            control_buttons_frame = ctk.CTkFrame(card_frame, fg_color="transparent")
            control_buttons_frame.pack(fill="x", pady=(2, 6), padx=10)
            
            # Бутон за избутване МАКСИМАЛНО НАВЪН (MAX OUT)
            out_btn = ctk.CTkButton(
                control_buttons_frame, 
                text="🟢 MAX OUT", 
                height=28, 
                fg_color=MATTE_GREEN, 
                hover_color=MATTE_GREEN_HOVER, 
                font=("Arial", 10, "bold"),
                command=lambda ch=channel: self.move_piston_and_read(ch, "OUT")
            )
            out_btn.pack(side="left", fill="x", expand=True, padx=(0, 3))
            
            # Бутон за прибиране МАКСИМАЛНО НАВЪТРЕ (MAX IN)
            in_btn = ctk.CTkButton(
                control_buttons_frame, 
                text="🔵 MAX IN", 
                height=28, 
                fg_color=MATTE_BLUE, 
                hover_color=MATTE_BLUE_HOVER, 
                font=("Arial", 10, "bold"),
                command=lambda ch=channel: self.move_piston_and_read(ch, "IN")
            )
            in_btn.pack(side="right", fill="x", expand=True, padx=(3, 0))
            
            self.inductance_value_vars.append(value_var)
            self.inductance_value_labels.append(value_label)
            self.inductance_channel_to_widget[channel] = i
            
            # Добавяме новите контролни бутони към масива за блокировка
            self.individual_piston_buttons.extend([out_btn, in_btn])
            last_row_index = i
            
            # Начертаваме първоначално празната скала за буталото
            self.draw_piston_gauge(i, "---")
            
        self.check_positions_btn = ctk.CTkButton(inductance_frame, text="Check Positions", height=35, width=180, command=self.start_inductance_check)
        self.check_positions_btn.grid(row=last_row_index + 1, column=0, pady=(15, 0), padx=10)

    # Функция за придвижване на бутало и АВТОМАТИЧНО отчитане на индуктивността веднага след движението!
    def move_piston_and_read(self, channel, direction):
        # 1. Изпращане на команда за соленоидите към Arduino
        self.send_command(f"P_{direction} {channel}")
        
        # 2. Таймер за софтуерно изчакване (например 1000ms), за да достигне буталото физически края,
        # и след това автоматично измерване на индуктивността за този канал!
        self.root.after(1000, lambda: self.start_single_inductance_check(channel))

    # ЧЕРТАНЕ НА АНАЛОГОВАТА СКАЛА ЗА БУТАЛАТА С ДВЕ ЗЕЛЕНИ ЗОНИ (Вдъхновена от резистивните сензори)
    def draw_piston_gauge(self, index, value_text):
        canvas = self.piston_canvases[index]
        canvas.delete("all")
        
        config = INDUCTANCE_DISPLAY_CONFIG[index]
        title, channel, min_val, in_start, in_end, out_start, out_end, max_val = config
        
        # Обща ширина на скалата в пиксели
        w_pixels = 420
        x_offset = 15
        
        # Нарисувай сивата фонова лента (скала от min_val до max_val)
        canvas.create_rectangle(x_offset, 8, x_offset + w_pixels, 18, fill="#444444", outline="")
        
        # Функция за конвектиране на стойност към X координата
        def val_to_x(val):
            ratio = (val - min_val) / float(max_val - min_val)
            if ratio < 0: ratio = 0.0
            if ratio > 1: ratio = 1.0
            return x_offset + ratio * w_pixels
            
        # Нарисувай ПЪРВАТА "зелена зона" (Гранични лимити за MAX IN)
        x_in_start = val_to_x(in_start)
        x_in_end = val_to_x(in_end)
        canvas.create_rectangle(x_in_start, 8, x_in_end, 18, fill=MATTE_GREEN, outline="")
        
        # Нарисувай ВТОРАТА "зелена зона" (Гранични лимити за MAX OUT)
        x_out_start = val_to_x(out_start)
        x_out_end = val_to_x(out_end)
        canvas.create_rectangle(x_out_start, 8, x_out_end, 18, fill=MATTE_GREEN, outline="")
        
        # Обозначаване на границите с ясни, видими текстове под скалата
        canvas.create_text(x_offset, 28, text=str(min_val), fill="#666666", font=("Arial", 9))
        canvas.create_text((x_in_start + x_in_end)/2, 28, text=f"IN: {in_start}-{in_end}", fill="#aaaaaa", font=("Arial", 9, "bold"))
        canvas.create_text((x_out_start + x_out_end)/2, 28, text=f"OUT: {out_start}-{out_end}", fill="#aaaaaa", font=("Arial", 9, "bold"))
        canvas.create_text(x_offset + w_pixels, 28, text=str(max_val), fill="#666666", font=("Arial", 9))
        
        try:
            clean_text = value_text.replace("uH", "").replace("mH", "").strip()
            val = float(clean_text)
            
            display_val = val
            if display_val < min_val: display_val = min_val
            if display_val > max_val: display_val = max_val
            
            x = val_to_x(display_val)
            
            # Нарисувай контрастна бяла стрелка за текущата измерена индуктивност
            canvas.create_line(x, 0, x, 19, fill="white", width=2)
            canvas.create_polygon(x-4, 0, x+4, 0, x, 5, fill="white")
        except:
            pass

    def build_right_panel(self, parent):
        pass

    def build_tests_panel(self, parent):
        tests_frame = ctk.CTkFrame(parent, corner_radius=10)
        tests_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        
        ctk.CTkLabel(tests_frame, text="Run a single test profile", font=("Arial", 11, "bold")).grid(row=0, column=0, columnspan=3, padx=5, pady=5)
        for idx, test_name in enumerate(TEST_NAMES):
            row = idx // 3 + 1
            col = idx % 3
            btn = ctk.CTkButton(
                tests_frame, 
                text=f"Test {test_name}", 
                width=110, 
                height=30,
                fg_color="#333333",
                hover_color="#555555",
                command=lambda name=test_name: self.run_test(name)
            )
            btn.grid(row=row, column=col, padx=4, pady=4, sticky="ew")
            self.predefined_buttons.append(btn)

    def build_auto_panel(self, parent):
        auto_frame = ctk.CTkFrame(parent, corner_radius=10)
        auto_frame.grid(row=1, column=0, sticky="nsew")
        
        self.auto_start_btn = ctk.CTkButton(auto_frame, text="Start Auto Sequence", fg_color=MATTE_GREEN, hover_color=MATTE_GREEN_HOVER, command=self.start_auto_sequence)
        self.auto_start_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.auto_stop_btn = ctk.CTkButton(auto_frame, text="Stop Auto Sequence", fg_color=MATTE_RED, hover_color=MATTE_RED_HOVER, command=self.stop_auto_sequence)
        self.auto_stop_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        self.auto_progress = ttk.Progressbar(auto_frame, orient="horizontal", mode="determinate", maximum=len(TEST_NAMES))
        self.auto_progress.grid(row=1, column=0, columnspan=2, padx=5, pady=10, sticky="ew")
        
        ctk.CTkLabel(auto_frame, text="Execution order", font=("Arial", 11, "bold")).grid(row=2, column=0, columnspan=2, padx=5, pady=5)
        self.sequence_listbox = tk.Listbox(auto_frame, font=("Consolas", 10), bg="#222222", fg="white", selectbackground=MATTE_BLUE, bd=0, highlightthickness=0)
        self.sequence_listbox.grid(row=3, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        auto_frame.columnconfigure(0, weight=1)
        auto_frame.columnconfigure(1, weight=1)
        auto_frame.rowconfigure(3, weight=1)
    
    def build_log_panel(self, parent):
        log_frame = ctk.CTkFrame(parent, corner_radius=10)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, font=("Consolas", 10), bg="#1e1e1e", fg="#9cdcfe", bd=0, highlightthickness=0, insertbackground="white")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)

    def start_sensor_check(self):
        serial_no = self.serial_var.get().strip()
        if serial_no:
            self.log(f"--- SENSOR CHECK for Serial: {serial_no} ---")
        for i in range(len(self.sensor_value_vars)):
            self.sensor_value_vars[i].set("Waiting...")
            self.sensor_value_labels[i].configure(fg_color="orange", text_color="black")
        self.send_command("READSENSORS")

    def start_inductance_check(self):
        serial_no = self.serial_var.get().strip()
        if serial_no:
            self.log(f"--- INDUCTANCE CHECK for Serial: {serial_no} ---")
        for i in range(len(self.inductance_value_vars)):
            self.inductance_value_vars[i].set("Waiting...")
            self.inductance_value_labels[i].configure(fg_color="orange", text_color="black")
        self.send_command("READINDUCTANCE")

    def start_single_inductance_check(self, channel):
        serial_no = self.serial_var.get().strip()
        if serial_no:
            self.log(f"--- SINGLE INDUCTANCE CHECK (CH {channel}) for Serial: {serial_no} ---")
        widget_index = self.inductance_channel_to_widget.get(channel)
        if widget_index is not None:
            self.inductance_value_vars[widget_index].set("Waiting...")
            self.inductance_value_labels[widget_index].configure(fg_color="orange", text_color="black")
        self.send_command(f"READINDUCTANCE {channel}")

    def check_overtemp(self):
        current_time = time.time()
        for channel, start_time in list(self.solenoid_on_times.items()):
            on_duration = current_time - start_time
            label = self.overtemp_labels[channel - 1]
            if on_duration > OVERTEMP_CRIT_SECONDS:
                label.configure(text="OVERTEMP", fg_color=MATTE_RED, text_color="white")
            elif on_duration > OVERTEMP_WARN_SECONDS:
                label.configure(text="Warning", fg_color="orange", text_color="black")
            else:
                label.configure(text="OK", fg_color=MATTE_GREEN, text_color="white")
        self.root.after(2000, self.check_overtemp)

    def set_state(self, channel, state):
        index = channel - 1
        if not (0 <= index < len(self.state_vars)): return
        self.current_states[index] = state
        self.state_vars[index].set(state)
        
        state_label = self.state_labels[index]
        overtemp_label = self.overtemp_labels[index]
        if state == "ON":
            state_label.configure(fg_color=MATTE_GREEN, text_color="white")
            if channel not in self.solenoid_on_times:
                self.solenoid_on_times[channel] = time.time()
            overtemp_label.configure(text="OK", fg_color=MATTE_GREEN, text_color="white")
        else:
            state_label.configure(fg_color=MATTE_RED if state == "OFF" else "#444444", text_color="white")
            if channel in self.solenoid_on_times:
                del self.solenoid_on_times[channel]
            overtemp_label.configure(text="Standby", fg_color=MATTE_GRAY, text_color="white")
    
    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo.configure(values=ports)
        if ports:
            self.port_combo.set(ports[0])
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
        self.update_interlock_states()

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
            
            self.serial_logged = False
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
        if value >= 1_000_000: return f"{value / 1_000_000:.2f} M\u03a9"
        if value >= 1_000: return f"{value / 1_000:.2f} k\u03a9"
        return f"{value:.0f} \u03a9"

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
        self.draw_sensor_gauge(widget_index, raw_value)
        
        try:
            clean_text = raw_value.replace("\u03a9", "").replace("k\u03a9", "").replace("M\u03a9", "").strip()
            val = float(clean_text)
            if 65 <= val <= 75:
                label.configure(fg_color=MATTE_GREEN, text_color="white")
            else:
                label.configure(fg_color=MATTE_RED, text_color="white")
        except (ValueError, TypeError):
            label.configure(fg_color="#444444", text_color="white")

    def apply_inductance_style(self, widget_index, raw_value):
        label = self.inductance_value_labels[widget_index]
        self.draw_piston_gauge(widget_index, raw_value)
        
        try:
            val = float(raw_value)
            config = INDUCTANCE_DISPLAY_CONFIG[widget_index]
            title, channel, min_val, in_start, in_end, out_start, out_end, max_val = config
            
            # Ако стойността попада в някоя от двете зелени зони, оцветяваме лейбъла в зелено!
            if (in_start <= val <= in_end) or (out_start <= val <= out_end):
                label.configure(fg_color=MATTE_GREEN, text_color="white")
            else:
                label.configure(fg_color=MATTE_RED, text_color="white")
        except (ValueError, TypeError):
            label.configure(fg_color="#444444", text_color="white")
    
    def apply_pressure_style(self, raw_value):
        label = self.pressure_value_label
        try:
            float(raw_value)
            label.configure(fg_color=MATTE_BLUE, text_color="white")
        except (ValueError, TypeError):
            label.configure(fg_color="#333333", text_color="white")

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
        
        try:
            with open("tester_log.txt", "a", encoding="utf-8") as f:
                timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
                f.write(f"{timestamp} {message}\n")
        except Exception as e:
            pass

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
    root = ctk.CTk()
    app = SolenoidApp(root)
    root.mainloop()
