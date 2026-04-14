import tkinter as tk
from tkinter import messagebox, ttk
import serial
import serial.tools.list_ports
import time

# --- Константи ---
SOLENOID_NAMES = ["Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9", "Y1", "Y10"]
TEST_NAMES = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "RL", "RH"]
SENSOR_DISPLAY_CONFIG = [("Sensor 1", 1), ("Sensor 2", 2), ("Sensor 3", 3), ("Sensor 4", 4)]

OVERTEMP_WARN_SECONDS = 60
OVERTEMP_CRIT_SECONDS = 120

class SolenoidApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ZF GS3 Solenoid Tester")
        self.root.geometry("1800x800")
        self.root.minsize(1500, 700)
        
        self.default_bg_color = self.root.cget('bg')

        app_frame = ttk.Frame(root)
        app_frame.pack(fill="both", expand=True)

        self.ser = None
        self.state_vars = []
        self.state_labels = []
        self.sensor_value_vars = []
        self.sensor_value_labels = []
        self.sensor_channel_to_widget = {}
        self.current_states = ["UNKNOWN"] * len(SOLENOID_NAMES)
        self.auto_sequence_states = ["pending"] * len(TEST_NAMES)
        self.last_auto_step_name = "-"
        
        self.overtemp_labels = []
        self.solenoid_on_times = {}

        self.build_top_panel(app_frame)
        self.build_info_panel(app_frame)
        
        center_frame = ttk.Frame(app_frame)
        center_frame.pack(fill="both", expand=True, padx=10, pady=5)
        center_frame.rowconfigure(0, weight=1)
        center_frame.columnconfigure(0, weight=3)
        center_frame.columnconfigure(1, weight=1)
        center_frame.columnconfigure(2, weight=1)

        self.build_solenoid_panel(center_frame)
        self.build_sensor_panel(center_frame)
        self.build_right_panel(center_frame)
        self.build_log_panel(app_frame)

        self.refresh_ports()
        self.refresh_auto_sequence_list()
        self.reset_sensor_cards()
        self.poll_serial()
        self.check_overtemp()

    def build_top_panel(self, parent):
        top_frame = ttk.Frame(parent, padding=(10, 10, 10, 0))
        top_frame.pack(fill="x")
        ttk.Label(top_frame, text="COM Port:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top_frame, textvariable=self.port_var, width=18, state="readonly")
        self.port_combo.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Button(top_frame, text="Refresh Ports", command=self.refresh_ports).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(top_frame, text="Connect", command=self.connect_serial).grid(row=0, column=3, padx=5, pady=5)
        ttk.Button(top_frame, text="Disconnect", command=self.disconnect_serial).grid(row=0, column=4, padx=5, pady=5)
        ttk.Button(top_frame, text="Read States", command=self.request_full_status).grid(row=0, column=5, padx=5, pady=5)
        ttk.Button(top_frame, text="Read Sensors Once", command=lambda: self.send_command("READSENSORS")).grid(row=0, column=6, padx=5, pady=5)
        ttk.Button(top_frame, text="Live ON", command=lambda: self.send_command("STREAM ON")).grid(row=0, column=7, padx=5, pady=5)
        ttk.Button(top_frame, text="Live OFF", command=lambda: self.send_command("STREAM OFF")).grid(row=0, column=8, padx=5, pady=5)

    def build_info_panel(self, parent):
        info_frame = ttk.LabelFrame(parent, text="Status", padding=10)
        info_frame.pack(fill="x", padx=10, pady=5)
        self.connection_var = tk.StringVar(value="Not connected")
        self.mode_var = tk.StringVar(value="Mode: Unknown")
        self.stream_var = tk.StringVar(value="Sensor stream: Unknown")
        self.auto_state_var = tk.StringVar(value="Auto sequence: STOPPED")
        self.auto_current_var = tk.StringVar(value="Current step: -")
        ttk.Label(info_frame, textvariable=self.connection_var).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ttk.Label(info_frame, textvariable=self.mode_var, font=("Arial", 10, "bold")).grid(row=0, column=1, padx=20, pady=5, sticky="w")
        ttk.Label(info_frame, textvariable=self.stream_var, font=("Arial", 10, "bold")).grid(row=0, column=2, padx=20, pady=5, sticky="w")
        ttk.Label(info_frame, textvariable=self.auto_state_var, font=("Arial", 10, "bold")).grid(row=1, column=0, padx=5, pady=5, sticky="w")
        ttk.Label(info_frame, textvariable=self.auto_current_var, font=("Arial", 10, "bold")).grid(row=1, column=1, columnspan=2, padx=20, pady=5, sticky="w")

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
            ttk.Button(solenoid_frame, text="ON", width=10, command=lambda ch=i: self.send_command(f"SET {ch} ON")).grid(row=i, column=2, padx=5, pady=6)
            ttk.Button(solenoid_frame, text="OFF", width=10, command=lambda ch=i: self.send_command(f"SET {ch} OFF")).grid(row=i, column=3, padx=5, pady=6)
            self.state_vars.append(state_var)
            self.state_labels.append(state_label)
            
            overtemp_label = tk.Label(solenoid_frame, text="Standby", width=12, bg="lightgrey", fg="black", font=("Arial", 9, "bold"), anchor="center")
            overtemp_label.grid(row=i, column=4, padx=10, pady=6)
            self.overtemp_labels.append(overtemp_label)

        separator = ttk.Separator(solenoid_frame, orient="horizontal")
        separator.grid(row=len(SOLENOID_NAMES) + 1, column=0, columnspan=5, sticky="ew", pady=10)
        
        all_off_button = ttk.Button(solenoid_frame, text="Turn All Solenoids OFF", command=lambda: self.send_command("SETOFF ALL"))
        all_off_button.grid(row=len(SOLENOID_NAMES) + 2, column=0, columnspan=5, sticky="ew", padx=5, pady=5)

    def build_sensor_panel(self, parent):
        sensor_frame = ttk.LabelFrame(parent, text="Sensors", padding=10)
        sensor_frame.grid(row=0, column=1, sticky="ns", padx=5)
        sensor_frame.columnconfigure(0, weight=1)
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

    def build_right_panel(self, parent):
        right_frame = ttk.Frame(parent)
        right_frame.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        right_frame.rowconfigure(1, weight=1)
        self.build_tests_panel(right_frame)
        self.build_auto_panel(right_frame)

    def build_tests_panel(self, parent):
        tests_frame = ttk.LabelFrame(parent, text="Predefined Tests", padding=10)
        tests_frame.grid(row=0, column=0, sticky="new")
        ttk.Label(tests_frame, text="Run a single test profile", font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=3, padx=5, pady=10)
        for idx, test_name in enumerate(TEST_NAMES):
            row = idx // 3 + 1
            col = idx % 3
            ttk.Button(tests_frame, text=f"Test {test_name}", width=12, command=lambda name=test_name: self.run_test(name)).grid(row=row, column=col, padx=5, pady=5, sticky="ew")

    def build_auto_panel(self, parent):
        auto_frame = ttk.LabelFrame(parent, text="Automatic Sequence", padding=10)
        auto_frame.grid(row=1, column=0, sticky="nsew", pady=(10,0))
        ttk.Button(auto_frame, text="Start Auto Sequence", command=self.start_auto_sequence).grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        ttk.Button(auto_frame, text="Stop Auto Sequence", command=self.stop_auto_sequence).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.auto_progress = ttk.Progressbar(auto_frame, orient="horizontal", mode="determinate", maximum=len(TEST_NAMES))
        self.auto_progress.grid(row=1, column=0, columnspan=2, padx=5, pady=10, sticky="ew")
        ttk.Label(auto_frame, text="Execution order", font=("Arial", 10, "bold")).grid(row=2, column=0, columnspan=2, padx=5, pady=5)
        self.sequence_listbox = tk.Listbox(auto_frame, font=("Consolas", 10))
        self.sequence_listbox.grid(row=3, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        auto_frame.columnconfigure(0, weight=1)
        auto_frame.columnconfigure(1, weight=1)
        auto_frame.rowconfigure(3, weight=1)
    
    def build_log_panel(self, parent):
        log_frame = ttk.LabelFrame(parent, text="Serial Log", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(log_frame, height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True)

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
            self.root.after(2000, self.post_connect_setup)
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))

    def post_connect_setup(self):
        self.request_full_status()
        self.send_command("AUTO STATUS")
        self.send_command("STREAM ON")

    def disconnect_serial(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(b"STREAM OFF\n")
            except Exception: pass
            self.ser.close()
            self.connection_var.set("Disconnected")
            self.mode_var.set("Mode: Unknown")
            self.stream_var.set("Sensor stream: Unknown")
            self.auto_state_var.set("Auto sequence: STOPPED")
            self.auto_current_var.set("Current step: -")
            self.reset_solenoid_states()
            self.reset_sensor_cards()
            self.log(f"Disconnected")

    def send_command(self, cmd):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Warning", "Not connected to Arduino.")
            return
        try:
            self.ser.write((cmd + "\n").encode("utf-8"))
            if not cmd.startswith("STREAM"):
                 self.log(f"PC -> Arduino: {cmd}")
        except Exception as e:
            messagebox.showerror("Send Error", str(e))

    def request_full_status(self):
        self.send_command("GETMODE")
        self.send_command("GETALL")
        self.send_command("READSENSORS")

    def run_test(self, test_name):
        self.send_command(f"TEST {test_name}")

    def start_auto_sequence(self):
        self.reset_auto_sequence_view()
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

    def apply_sensor_style(self, widget_index, raw_value):
        label = self.sensor_value_labels[widget_index]
        try:
            float(raw_value)
            label.config(bg="#1565c0", fg="white")
        except (ValueError, TypeError):
            label.config(bg="#808080", fg="white")

    def reset_sensor_cards(self):
        for i in range(len(self.sensor_value_vars)):
            self.sensor_value_vars[i].set("---")
            self.apply_sensor_style(i, "---")

    def reset_solenoid_states(self):
        for i in range(len(SOLENOID_NAMES)):
            self.set_state(i + 1, "UNKNOWN")

    def set_resistance(self, channel, value_text):
        widget_index = self.sensor_channel_to_widget.get(channel)
        if widget_index is None: return
        self.sensor_value_vars[widget_index].set(self.format_resistance(value_text))
        self.apply_sensor_style(widget_index, value_text)

    def parse_serial_line(self, line):
        if not line: return
        if line.startswith("SENSORS "):
            self.parse_sensors(line)
            return
        self.log(f"Arduino -> PC: {line}")
        parts = line.split()
        if not parts: return
        cmd = parts[0]
        if cmd == "READY": self.log("Arduino is ready.")
        elif cmd == "MODE": self.mode_var.set(f"Mode: {line.split(maxsplit=1)[1]}")
        elif cmd == "STREAM": self.stream_var.set(f"Sensor stream: {line.split(maxsplit=1)[1]}")
        elif cmd == "AUTO_STATE": self.auto_state_var.set(f"Auto sequence: {line.split(maxsplit=1)[1].upper()}")
        elif cmd == "AUTO_DONE": self.complete_auto_sequence()
        elif cmd == "APPLIED_TEST": self.log(f"Applied test: {line.split(maxsplit=1)[1]}")
        elif cmd == "ERROR": self.log(f"Arduino error: {line.split(maxsplit=1)[1]}")
        elif cmd == "ALL": self.parse_all_states(line)
        elif cmd == "AUTO_STEP":
            if len(parts) == 4 and parts[1].isdigit() and parts[2].isdigit():
                self.update_auto_step(int(parts[1]), int(parts[2]), parts[3])
        elif cmd in ("SOL", "STATE"):
            if len(parts) == 3 and parts[1].isdigit():
                self.set_state(int(parts[1]), parts[2].upper())

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

if __name__ == "__main__":
    root = tk.Tk()
    app = SolenoidApp(root)
    root.mainloop()
