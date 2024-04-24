import RPi.GPIO as GPIO
import time

# Set pin numbering mode (BCM or BOARD)
GPIO.setmode(GPIO.BCM)

# Define the servo pin
servo_pin = 2

# Set up GPIO pin as output
GPIO.setup(servo_pin, GPIO.OUT)

# Set up PWM on the servo pin at 50Hz frequency
pwm = GPIO.PWM(servo_pin, 50)

# Function to set the servo angle
def set_angle(angle):
    """
    Sets the servo motor to a specified angle.

    Args:
        angle (int): The desired angle for the servo (in degrees).
    """

    # Calculate duty cycle based on angle (adjust range based on your servo)
    duty_cycle = (angle / 18) + 2  # Adjust 2 for minimum pulse width

    # Start PWM output
    pwm.start(duty_cycle)

    # Wait for the servo to reach its position
    time.sleep(1)  # Adjust sleep time based on your servo speed

    # Stop PWM output
    pwm.stop()

# Try-except block for proper cleanup
try:
    # Set the servo to 90 degrees (example)
    set_angle(180)

except KeyboardInterrupt:
    # User pressed Ctrl+C, so clean up
    pwm.stop()
    GPIO.cleanup()
    print("Exiting program...")

finally:
    # Ensure GPIO cleanup even if exceptions occur
    GPIO.cleanup()
    print("GPIO resources cleaned up.")
