import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)  # Ignore deprecation warnings

import sys
import serial
import serial.tools.list_ports
from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, QElapsedTimer
from PyQt6.QtWidgets import QMessageBox, QLabel, QVBoxLayout, QProgressBar, QTextEdit, QPushButton, QMainWindow, QApplication, QDialog

class Worker(QThread):
    # Custom signals for communication with the main thread
    log_signal = pyqtSignal(int, str)  # Signal to send log messages (board_id, log message)
    error_signal = pyqtSignal(int, str)  # Signal to send error messages (board_id, error message)
    flashed_signal = pyqtSignal(int)  # Signal to indicate flashing is complete (board_id)
    first_transmission_signal = pyqtSignal(int)  # Signal for the first transmission (board_id)

    def __init__(self, port, baudrate, board_id, parent=None):
        super(Worker, self).__init__(parent)
        self.port = port  # Serial port to communicate with the board
        self.baudrate = baudrate  # Baudrate for the serial communication
        self.board_id = board_id  # ID of the board being monitored
        self.running = True  # Control flag for the thread
        self.first_transmission_received = False  # Flag to indicate if the first transmission has been received

    def run(self):
        # Main method of the thread
        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=1)  # Open the serial port
            while self.running:
                if ser.in_waiting > 0:  # Check if there is data waiting in the serial buffer
                    try:
                        data = ser.readline().decode('utf-8', errors='ignore').strip()  # Read and decode the data
                    except UnicodeDecodeError as e:
                        self.error_signal.emit(self.board_id, f"Decoding error: {e}")  # Emit error signal if decoding fails
                        continue
                    if not self.first_transmission_received:
                        self.first_transmission_received = True
                        self.first_transmission_signal.emit(self.board_id)  # Emit signal for the first transmission
                    self.log_signal.emit(self.board_id, data)  # Emit log signal with the received data
                    if "Span Gateway 2.0.0 span-gateway" in data:  # Check for specific message indicating flashing is done
                        self.flashed_signal.emit(self.board_id)  # Emit flashed signal if flashing is done
                self.msleep(100)  # Sleep for a short while to avoid busy waiting
        except serial.SerialException as e:
            self.error_signal.emit(self.board_id, f"Serial port error: {e}")  # Emit error signal if serial port fails
        finally:
            if ser.is_open:
                ser.close()  # Close the serial port when done

    def stop(self):
        # Method to stop the thread
        self.running = False

class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.setWindowTitle("Firmware Flash Monitoring")
        self.setGeometry(100, 100, 800, 600)

        # Create central widget and layout
        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.board_layout = QVBoxLayout()  # Layout for the boards' widgets
        self.layout.addLayout(self.board_layout)

        # Add buttons
        self.add_button = QPushButton("Add Board")
        self.add_button.clicked.connect(self.add_boards)  # Connect button to method to add boards
        self.layout.addWidget(self.add_button)

        self.restart_button = QPushButton("Restart Program")
        self.restart_button.clicked.connect(self.restart_program)  # Connect button to method to restart the program
        self.layout.addWidget(self.restart_button)

        # Initialize lists for storing workers, progress bars, logs, timers, and time labels
        self.workers = []  # List to store worker threads
        self.progress_bars = []  # List to store progress bars
        self.text_logs = []  # List to store text logs
        self.timers = []  # List to store progress timers
        self.time_labels = []  # List to store time labels
        self.elapsed_timers = []  # List to store QElapsedTimer instances
        self.progress_timers = []  # List to store progress timers for each board
        self.time_timers = []  # List to store time update timers for each board

    def add_boards(self):
        # Method to detect and add all available boards
        ports = serial.tools.list_ports.comports()  # Get all available serial ports
        baudrate = 115200  # Define baudrate for serial communication
        
        # Loop through each detected port and add it as a board
        for port in ports:
            board_id = len(self.workers)  # Assign a new board ID
            self.add_board(port.device, baudrate, board_id)  # Add board with specified port and baudrate

    def add_board(self, port, baudrate, board_id):
        # Method to add a single board and set up its UI components and worker thread
        progress_bar = QProgressBar(self)
        text_log = QTextEdit(self)
        time_label = QLabel(self)  # Label to display elapsed time
        progress_bar.setRange(0, 100)  # Set progress bar range

        # Add widgets to the layout
        self.board_layout.addWidget(QLabel(f"Board {board_id+1} ({port}) Progress:"))
        self.board_layout.addWidget(progress_bar)
        self.board_layout.addWidget(QLabel(f"Board {board_id+1} ({port}) Log:"))
        self.board_layout.addWidget(time_label)
        self.board_layout.addWidget(text_log)

        # Store references to the UI components
        self.progress_bars.append(progress_bar)
        self.text_logs.append(text_log)
        self.time_labels.append(time_label)

        # Create and start a worker thread for the board
        worker = Worker(port, baudrate, board_id)
        worker.log_signal.connect(self.update_log)  # Connect worker signals to respective handlers
        worker.error_signal.connect(self.handle_error)
        worker.flashed_signal.connect(self.handle_flashed)
        worker.first_transmission_signal.connect(lambda: self.start_timers(board_id))  # Start timers on first transmission
        self.workers.append(worker)
        worker.start()

        # Initialize timers with placeholders
        self.elapsed_timers.append(None)
        self.progress_timers.append(None)
        self.time_timers.append(None)

    def start_timers(self, board_id):
        # Method to start the progress and elapsed time timers
        # Start the elapsed timer for tracking flashing time
        elapsed_timer = QElapsedTimer()
        elapsed_timer.start()
        self.elapsed_timers[board_id] = elapsed_timer

        # Set up a timer to update the progress bar periodically
        progress_timer = QTimer(self)
        progress_timer.timeout.connect(lambda: self.update_progress(board_id, self.progress_bars[board_id], progress_timer, self.workers[board_id]))
        progress_timer.start(10000)  # Update every 10 seconds
        self.progress_timers[board_id] = progress_timer

        # Set up a timer to update the elapsed time label
        time_timer = QTimer(self)
        time_timer.timeout.connect(lambda: self.update_time(board_id))
        time_timer.start(1)  # Update every millisecond
        self.time_timers[board_id] = time_timer

    def update_progress(self, board_id, progress_bar, timer, worker):
        # Method to update the progress bar value
        value = progress_bar.value()
        if value < 100:
            value += 100 / 77  # Increment progress (total time is 12 minutes 50 seconds, 77 ten-second intervals)
            progress_bar.setValue(int(value))  # Ensure value is an integer
        else:
            timer.stop()  # Stop the timer when progress is complete
            progress_bar.setValue(100)  # Set progress bar to 100%
            self.text_logs[board_id].append("This board is flashed successfully")
            worker.stop()  # Stop the worker thread

    def update_log(self, board_id, message):
        # Method to append log messages to the text log
        self.text_logs[board_id].append(message)

    def update_time(self, board_id):
        # Method to update the elapsed time label
        elapsed = self.elapsed_timers[board_id].elapsed()  # Get elapsed time in milliseconds
        milliseconds = elapsed % 1000
        seconds = (elapsed // 1000) % 60
        minutes = (elapsed // 60000) % 60
        hours = (elapsed // 3600000) % 24
        current_time = f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"  # Format time as HH:MM:SS.mmm
        self.time_labels[board_id].setText(current_time)  # Update the label

    def handle_error(self, board_id, error_message):
        # Method to handle errors by displaying a message box and logging the error
        self.text_logs[board_id].append(f"Error: {error_message}")
        QMessageBox.critical(self, "Serial Port Error", f"Board {board_id+1} encountered an error: {error_message}")

    def handle_flashed(self, board_id):
        # Method to handle successful flashing by updating the progress bar and showing a custom message box
        self.progress_bars[board_id].setValue(100)
        self.text_logs[board_id].append("Firmware flashing completed")

        # Create a custom dialog for the success message
        success_dialog = QDialog(self)
        success_dialog.setWindowTitle("Board Flash Complete")
        success_dialog.setGeometry(100, 100, 400, 200)  # Set the size of the dialog
        success_dialog.setStyleSheet("background-color: green;")  # Set the background color to green

        # Create a label to display the success message
        success_label = QLabel(f"Board {board_id+1} passed", success_dialog)
        success_label.setStyleSheet("color: white; font-size: 24px; font-weight: bold;")
        success_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Create a layout for the dialog and add the label to it
        dialog_layout = QVBoxLayout(success_dialog)
        dialog_layout.addWidget(success_label)

        # Show the dialog
        success_dialog.exec()

    def restart_program(self):
        # Method to restart the program
        QMessageBox.information(self, "Program Restart", "The program will restart.")
        QtCore.QCoreApplication.quit()  # Quit the current application
        QtCore.QProcess.startDetached(sys.executable, sys.argv)  # Start a new instance of the application

    def closeEvent(self, event):
        # Overridden method to handle the window close event
        for worker in self.workers:
            worker.stop()  # Stop all worker threads
            worker.wait()  # Wait for the threads to finish
        for timer in self.timers:
            timer.stop()  # Stop all timers
        event.accept()  # Accept the close event

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()  # Create main window
    window.show()  # Show the main window
    sys.exit(app.exec())  # Run the application event loop
