import logging
import sys

def default_logger_config(logger: logging.Logger) -> None:
    """
    Configure the default logger for the application.
    
    This function sets up a basic logging configuration that outputs
    logs to the console with a specific format.
    """
    logger.setLevel(logging.INFO) # Or logging.DEBUG for more verbose output
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(lineno)d - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)