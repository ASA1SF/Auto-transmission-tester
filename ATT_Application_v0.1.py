import tkinter as tk
from tkinter import messagebox, ttk

import serial
import serial.tools.list_ports

SOLENOID_NAMES = [
    "Y2",
    "Y3",
    "Y4",
    "Y5",
    "Y6",
    "Y7",
    "Y8",
    "Y9",
    "Y1",
    "Y10",
]

TEST_NAMES = [
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "11",
    "12",
    "RL",
    "RH",
]

# Кои 4 сензорни канала да се виждат в средната зона
# Формат: ("Име", channel_number_from_serial)
SENSOR_DISPLAY_CONFIG = [
    ("Sensor 1", 1),
    ("Sensor 2", 2),
    ("Sensor 3", 3),
    ("Sensor 4", 4),
]


class SolenoidApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ZF GS3 Solenoid Tester")

        try:
            self.root.state("zoomed")
        except tk.TclError:
            self.root.geometry("1500x900")

        self.root.minsize(1280, 760)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.ser = None

        self.state_vars = []
        self.state_labels = []

        self.sensor_value_vars = []
        self.sensor_value_labels = []
        self.sensor_channel_to_widget = {}

        self.current_states = ["UNKNOWN"] * len(SOLENOID_NAMES)
        self.current_resistance_raw = ["UNKNOWN"] * len(SOLENOID_NAMES)
        self.current_mode_text = "UNKNOWN"

        self.auto_sequence_states = ["pending"] * len(TEST_NAMES)
        self.last_auto_step_name = "-"
        self.last_auto_step_index = None

        self.build_top_panel()
        self.build_info_panel()
        self.build_main_panel()

        self.refresh_ports()
        self.refresh_auto_sequence_list()
        self.reset_sensor_cards()
        self.poll_serial()

    def build_top_panel(self):
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill="x")

        ttk.Label(top_frame, text="COM Port:").grid(
            row=0, column=0, padx=5, pady=5, sticky="w"
        )

        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(
            top_frame,
            textvariable=self.port_var,
            width=18,
            state="readonly",
        )
        self.port_combo.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Button(
            top_frame,
            text="Refresh Ports",
            command=self.refresh_ports,
        ).grid(row=0, column=2, padx=5, pady=5)

        ttk.Button(
            top_frame,
            text="Connect",
            command=self.connect_serial,
        ).grid(row=0, column=3, padx=5, pady=5)

        ttk.Button(
            top_frame,
            text="Disconnect",
            command=self.disconnect_serial,
        ).grid(row=0, column=4, padx=5, pady=5)

        ttk.Button(
            top_frame,
            text="Read States",
            command=self.request_full_status,
        ).grid(row=0, column=5, padx=5, pady=5)

        ttk.Button(
            top_frame,
            text="Read Sensors Once",
            command=lambda: self.send_command("READSENSORS"),
        ).grid(row=0, column=6, padx=5, pady=5)

        ttk.Button(
            top_frame,
            text="Live ON",
            command=lambda: self.send_command("STREAM ON"),
        ).grid(row=0, column=7, padx=5, pady=5)

        ttk.Button(
            top_frame,
            text="Live OFF",
            command=lambda: self.send_command("STREAM OFF"),
        ).grid(row=0, column=8, padx=5, pady=5)

    def build_info_panel(self):
        info_frame = ttk.LabelFrame(self.root, text="Status", padding=10)
        info_frame.pack(fill="x", padx=10, pady=5)

        self.connection_var = tk.StringVar(value="Not connected")
        self.mode_var = tk.StringVar(value="Mode: Unknown")
        self.stream_var = tk.StringVar(value="Sensor stream: Unknown")
        self.auto_state_var = tk.StringVar(value="Auto sequence: STOPPED")
        self.auto_current_var = tk.StringVar(value="Current step: -")

        ttk.Label(info_frame, textvariable=self.connection_var).grid(
            row=0, column=0, padx=5, pady=5, sticky="w"
        )

        ttk.Label(
            info_frame,
            textvariable=self.mode_var,
            font=("Arial", 10, "bold"),
        ).grid(row=0, column=1, padx=20, pady=5, sticky="w")

        ttk.Label(
            info_frame,
            textvariable=self.stream_var,
            font=("Arial", 10, "bold"),
        ).grid(row=0, column=2, padx=20, pady=5, sticky="w")

        ttk.Label(
            info_frame,
            textvariable=self.auto_state_var,
            font=("Arial", 10, "bold"),
        ).grid(row=1, column=0, padx=5, pady=5, sticky="w")

        ttk.Label(
            info_frame,
            textvariable=self.auto_current_var,
            font=("Arial", 10, "bold"),
        ).grid(row=1, column=1, columnspan=2, padx=20, pady=5, sticky="w")

    def build_main_panel(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill="both", expand=True, padx=10, pady=5)

        main_frame.columnconfigure(0, weight=3, minsize=520)
        main_frame.columnconfigure(1, weight=2, minsize=420)
        main_frame.columnconfigure(2, weight=0, minsize=420)
        main_frame.rowconfigure(0, weight=1)

        left_container = ttk.Frame(main_frame)
        left_container.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        center_container = ttk.Frame(main_frame)
        center_container.grid(row=0, column=1, sticky="nsew", padx=(0, 10))

        right_container = ttk.Frame(main_frame)
        right_container.grid(row=0, column=2, sticky="ns")

        self.build_solenoid_panel(left_container)
        self.build_sensor_panel(center_container)
        self.build_tests_panel(right_container)
        self.build_auto_panel(right_container)

    def build_solenoid_panel(self, parent):
        solenoid_frame = ttk.LabelFrame(
            parent,
            text="Manual Solenoid Control",
            padding=10,
        )
        solenoid_frame.pack(fill="both", expand=True)

        ttk.Label(solenoid_frame, text="Channel", width=18).grid(
            row=0, column=0, padx=5, pady=5
        )
        ttk.Label(solenoid_frame, text="State", width=10).grid(
            row=0, column=1, padx=5, pady=5
        )
        ttk.Label(solenoid_frame, text="Control", width=20).grid(
            row=0, column=2, columnspan=2, padx=5, pady=5
        )

        for i, name in enumerate(SOLENOID_NAMES, start=1):
            ttk.Label(
                solenoid_frame,
                text=f"Solenoid {i} ({name})",
                width=18,
            ).grid(row=i, column=0, padx=5, pady=6, sticky="w")

            state_var = tk.StringVar(value="UNKNOWN")
            state_label = tk.Label(
                solenoid_frame,
                textvariable=state_var,
                width=10,
                bg="#808080",
                fg="white",
                relief="ridge",
                font=("Arial", 10, "bold"),
            )
            state_label.grid(row=i, column=1, padx=5, pady=6)

            ttk.Button(
                solenoid_frame,
                text="ON",
                width=10,
                command=lambda ch=i: self.send_command(f"SET {ch} ON"),
            ).grid(row=i, column=2, padx=5, pady=6)

            ttk.Button(
                solenoid_frame,
                text="OFF",
                width=10,
                command=lambda ch=i: self.send_command(f"SET {ch} OFF"),
            ).grid(row=i, column=3, padx=5, pady=6)

            self.state_vars.append(state_var)
            self.state_labels.append(state_label)

    def build_sensor_panel(self, parent):
        sensor_frame = ttk.LabelFrame(parent, text="Sensors", padding=10)
        sensor_frame.pack(fill="both", expand=True)

        ttk.Label(sensor_frame, text="Sensor", width=18).grid(
            row=0, column=0, padx=5, pady=5
        )
        ttk.Label(sensor_frame, text="Value", width=14).grid(
            row=0, column=1, padx=5, pady=5
        )

        for idx, (title, channel) in enumerate(SENSOR_DISPLAY_CONFIG, start=1):
            ttk.Label(
                sensor_frame,
                text=title,
                width=18,
            ).grid(row=idx, column=0, padx=5, pady=8, sticky="w")

            value_var = tk.StringVar(value="UNKNOWN")
            value_label = tk.Label(
                sensor_frame,
                textvariable=value_var,
                width=12,
                bg="#808080",
                fg="white",
                relief="ridge",
                font=("Arial", 10, "bold"),
            )
            value_label.grid(row=idx, column=1, padx=5, pady=8, sticky="ew")

            self.sensor_value_vars.append(value_var)
            self.sensor_value_labels.append(value_label)
            self.sensor_channel_to_widget[channel] = idx - 1


        sensor_frame.columnconfigure(0, weight=1)
        sensor_frame.columnconfigure(1, weight=1)

    def build_tests_panel(self, parent):
        tests_frame = ttk.LabelFrame(
            parent,
            text="Predefined Tests",
            padding=10,
        )
        tests_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(
            tests_frame,
            text="Run a single test profile",
            font=("Arial", 10, "bold"),
        ).grid(row=0, column=0, columnspan=3, padx=5, pady=10)

        for idx, test_name in enumerate(TEST_NAMES):
            row = idx // 3 + 1
            col = idx % 3

            ttk.Button(
                tests_frame,
                text=f"Test {test_name}",
                width=12,
                command=lambda name=test_name: self.run_test(name),
            ).grid(row=row, column=col, padx=5, pady=5, sticky="ew")

        for col in range(3):
            tests_frame.columnconfigure(col, weight=1)

    def build_auto_panel(self, parent):
        auto_frame = ttk.LabelFrame(
            parent,
            text="Automatic Sequence",
            padding=10,
        )
        auto_frame.pack(fill="both", expand=True)

        ttk.Button(
            auto_frame,
            text="Start Auto Sequence",
            command=self.start_auto_sequence,
        ).grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        ttk.Button(
            auto_frame,
            text="Stop Auto Sequence",
            command=self.stop_auto_sequence,
        ).grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.auto_progress = ttk.Progressbar(
            auto_frame,
            orient="horizontal",
            mode="determinate",
            maximum=len(TEST_NAMES),
            length=280,
        )
        self.auto_progress.grid(
            row=1, column=0, columnspan=2, padx=5, pady=10, sticky="ew"
        )

        ttk.Label(
            auto_frame,
            text="Execution order",
            font=("Arial", 10, "bold"),
        ).grid(row=2, column=0, columnspan=2, padx=5, pady=5)

        self.sequence_listbox = tk.Listbox(
            auto_frame,
            width=28,
            height=10,
            font=("Consolas", 10),
        )
        self.sequence_listbox.grid(
            row=3, column=0, columnspan=2, padx=5, pady=5, sticky="nsew"
        )

        auto_frame.columnconfigure(0, weight=1)
        auto_frame.columnconfigure(1, weight=1)
        auto_frame.rowconfigure(3, weight=1)

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
        if not self.ser or not self.ser.is_open:
            return

        self.request_full_status()
        self.send_command("AUTO STATUS")
        self.send_command("STREAM ON")

    def disconnect_serial(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(b"STREAM OFF\n")
            except Exception:
                pass

            port = self.ser.port
            self.ser.close()

            self.connection_var.set("Disconnected")
            self.mode_var.set("Mode: Unknown")
            self.stream_var.set("Sensor stream: Unknown")
            self.auto_state_var.set("Auto sequence: STOPPED")
            self.auto_current_var.set("Current step: -")
            self.current_mode_text = "UNKNOWN"

            self.reset_solenoid_states()
            self.reset_sensor_cards()

            self.log(f"Disconnected from {port}")

    def on_close(self):
        try:
            self.disconnect_serial()
        except Exception:
            pass

        self.root.destroy()

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

    def send_command(self, cmd):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Warning", "Not connected to Arduino.")
            return

        try:
            self.ser.write((cmd + "\n").encode("utf-8"))
            self.log(f"PC -> Arduino: {cmd}")
        except Exception as e:
            messagebox.showerror("Send Error", str(e))

    def reset_auto_sequence_view(self):
        self.auto_sequence_states = ["pending"] * len(TEST_NAMES)
        self.last_auto_step_name = "-"
        self.last_auto_step_index = None
        self.auto_progress["maximum"] = len(TEST_NAMES)
        self.auto_progress["value"] = 0
        self.auto_state_var.set("Auto sequence: STARTING...")
        self.auto_current_var.set("Current step: -")
        self.refresh_auto_sequence_list()

    def refresh_auto_sequence_list(self):
        self.sequence_listbox.delete(0, tk.END)

        current_index = None

        for idx, test_name in enumerate(TEST_NAMES):
            state = self.auto_sequence_states[idx]

            if state == "done":
                prefix = "[x]"
            elif state == "current":
                prefix = "[>]"
                current_index = idx
            else:
                prefix = "[ ]"

            self.sequence_listbox.insert(tk.END, f"{prefix} Test {test_name}")

        self.sequence_listbox.selection_clear(0, tk.END)

        if current_index is not None:
            self.sequence_listbox.selection_set(current_index)
            self.sequence_listbox.see(current_index)

    def update_auto_step(self, step_number, total_steps, test_name):
        step_index = step_number - 1

        if step_index < 0 or step_index >= len(TEST_NAMES):
            return

        self.last_auto_step_name = test_name
        self.last_auto_step_index = step_index

        for i in range(len(TEST_NAMES)):
            if i < step_index:
                self.auto_sequence_states[i] = "done"
            elif i == step_index:
                self.auto_sequence_states[i] = "current"
            else:
                self.auto_sequence_states[i] = "pending"

        self.auto_progress["maximum"] = total_steps
        self.auto_progress["value"] = step_number

        self.auto_state_var.set("Auto sequence: RUNNING")
        self.auto_current_var.set(
            f"Current step: {step_number}/{total_steps} - Test {test_name}"
        )

        self.refresh_auto_sequence_list()

    def complete_auto_sequence(self):
        for i in range(len(TEST_NAMES)):
            self.auto_sequence_states[i] = "done"

        self.auto_progress["value"] = len(TEST_NAMES)
        self.auto_state_var.set("Auto sequence: COMPLETED")
        self.auto_current_var.set(
            f"Current step: Completed - Last test {self.last_auto_step_name}"
        )
        self.refresh_auto_sequence_list()

    def format_ohms_value(self, value):
        if value >= 1000000:
            return f"{value / 1000000:.2f} MΩ"
        if value >= 1000:
            return f"{value / 1000:.2f} kΩ"

        return f"{value:.0f} Ω"

    def format_resistance(self, value_text):
        upper = str(value_text).upper()

        if upper in {"OPEN", "SHORT", "ERR", "UNKNOWN"}:
            return upper

        try:
            value = float(value_text)
        except ValueError:
            return str(value_text)

        return self.format_ohms_value(value)

    def apply_sensor_style(self, widget_index, raw_value):
        upper = str(raw_value).upper()

        if upper in {"ERR", "UNKNOWN", "---"}:
            self.sensor_value_labels[widget_index].config(
                bg="#808080",
                fg="white",
            )
        elif upper in {"OPEN", "SHORT"}:
            self.sensor_value_labels[widget_index].config(
                bg="#c62828",
                fg="white",
            )
        else:
            self.sensor_value_labels[widget_index].config(
                bg="#2e7d32",
                fg="white",
            )

    def reset_sensor_cards(self):
        for i in range(len(self.current_resistance_raw)):
            self.current_resistance_raw[i] = "UNKNOWN"

        for i, value_var in enumerate(self.sensor_value_vars):
            value_var.set("UNKNOWN")
            self.apply_sensor_style(i, "UNKNOWN")

    def reset_solenoid_states(self):
        for channel in range(1, len(SOLENOID_NAMES) + 1):
            self.set_state(channel, "UNKNOWN")

    def set_state(self, channel, state):
        index = channel - 1

        if index < 0 or index >= len(self.state_vars):
            return

        self.current_states[index] = state
        self.state_vars[index].set(state)

        if state == "ON":
            self.state_labels[index].config(bg="#2e7d32", fg="white")
        elif state == "OFF":
            self.state_labels[index].config(bg="#c62828", fg="white")
        else:
            self.state_labels[index].config(bg="#808080", fg="white")

    def set_resistance(self, channel, value_text):
        index = channel - 1

        if index < 0 or index >= len(self.current_resistance_raw):
            return

        self.current_resistance_raw[index] = value_text

        widget_index = self.sensor_channel_to_widget.get(channel)

        if widget_index is None:
            return

        self.sensor_value_vars[widget_index].set(
            self.format_resistance(value_text)
        )
        self.apply_sensor_style(widget_index, value_text)

    def parse_all_states(self, line):
        parts = line.split()[1:]

        for item in parts:
            if ":" not in item:
                continue

            channel_text, state = item.split(":", 1)

            if channel_text.isdigit():
                self.set_state(int(channel_text), state.upper())

    def parse_sensors(self, line):
        parts = line.split()[1:]

        for item in parts:
            if ":" not in item:
                continue

            channel_text, value_text = item.split(":", 1)

            if channel_text.isdigit():
                self.set_resistance(int(channel_text), value_text)

    def parse_serial_line(self, line):
        if line == "READY":
            self.log("Arduino is ready.")
            return

        if line.startswith("MODE "):
            mode_text = line[5:].strip()
            self.current_mode_text = mode_text.upper()
            self.mode_var.set(f"Mode: {mode_text}")
            return

        if line.startswith("STREAM "):
            stream_text = line[7:]
            self.stream_var.set(f"Sensor stream: {stream_text}")
            return

        if line.startswith("AUTO_STATE "):
            state_text = line[11:].strip().upper()

            if state_text == "RUNNING":
                self.auto_state_var.set("Auto sequence: RUNNING")
            elif state_text == "STOPPED":
                self.auto_state_var.set("Auto sequence: STOPPED")

            return

        if line.startswith("AUTO_STEP "):
            parts = line.split(maxsplit=3)

            if len(parts) == 4 and parts[1].isdigit() and parts[2].isdigit():
                step_number = int(parts[1])
                total_steps = int(parts[2])
                test_name = parts[3]
                self.update_auto_step(step_number, total_steps, test_name)

            return

        if line == "AUTO_DONE":
            self.complete_auto_sequence()
            return

        if line.startswith("TEST_APPLIED "):
            test_name = line.split(maxsplit=1)[1]
            self.log(f"Applied test: {test_name}")
            return

        if line.startswith("SOL ") or line.startswith("STATE "):
            parts = line.split()

            if len(parts) == 3 and parts[1].isdigit():
                channel = int(parts[1])
                state = parts[2].upper()
                self.set_state(channel, state)

            return

        if line.startswith("ALL "):
            self.parse_all_states(line)
            return

        if line.startswith("SENSORS "):
            self.parse_sensors(line)
            return

        if line.startswith("ERROR "):
            self.log(f"Arduino error: {line}")
            return

    def poll_serial(self):
        if self.ser and self.ser.is_open:
            try:
                while self.ser.in_waiting:
                    line = self.ser.readline().decode(
                        "utf-8",
                        errors="ignore",
                    ).strip()

                    if not line:
                        continue

                    self.log(f"Arduino -> PC: {line}")
                    self.parse_serial_line(line)
            except Exception as e:
                self.log(f"Read error: {e}")

        self.root.after(100, self.poll_serial)

    def log(self, message):
        print(message)


if __name__ == "__main__":
    root = tk.Tk()
    app = SolenoidApp(root)
    root.mainloop()