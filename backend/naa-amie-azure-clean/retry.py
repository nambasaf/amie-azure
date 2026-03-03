import time
import random
import logging

# ---------------------------------------------------------------------
# RETRY WRAPPER
# ---------------------------------------------------------------------
def retry_agent(callable_fn, agent_name: str, max_attempts: int = 5):
    """
    Retry wrapper for agents with bounded attempts and exponential backoff.
    
    Args:
        callable_fn: A callable (lambda or function) that executes the agent
        agent_name: Human-readable name for logging (e.g., "IDCA Agent")
        max_attempts: Maximum number of retry attempts before failing.
    
    Returns:
        The result of callable_fn on first successful execution
    
    Raises:
        The last exception encountered if max_attempts is reached.
    """
    last_exception = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            return callable_fn()
        except Exception as e:
            last_exception = e
            logging.warning(f"[RETRY] {agent_name} failed (Attempt {attempt}/{max_attempts}): {e}")
            
            if attempt < max_attempts:
                # Exponential backoff: 2s, 4s, 8s, 16s... + jitter
                sleep_time = (2 ** attempt) + (random.uniform(0, 1))
                logging.info(f"Retrying {agent_name} in {sleep_time:.2f}s...")
                time.sleep(sleep_time)
            else:
                logging.error(f"[RETRY] {agent_name} exhausted all {max_attempts} attempts.")
    
    raise last_exception