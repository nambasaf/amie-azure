
# ---------------------------------------------------------------------
# RETRY WRAPPER
# ---------------------------------------------------------------------
def retry_agent(callable_fn, agent_name: str):
    """
    Retry wrapper for NAA agents (Steps 8-11).
    
    Executes the callable inside a while True loop.
    Catches all exceptions and retries until success.
    Logs each failure and retry attempt.
    
    Args:
        callable_fn: A callable (lambda or function) that executes the agent
        agent_name: Human-readable name for logging (e.g., "SS Agent")
    
    Returns:
        The result of callable_fn on first successful execution
    """
    import time
    
    attempts = 0
    MAX_RETRIES = 3
    
    while attempts < MAX_RETRIES:
        try:
            result = callable_fn()
            return result
        except Exception as e:
            attempts += 1
            print(f"\n[RETRY] {agent_name} failed (Attempt {attempts}/{MAX_RETRIES}):")
            print(f"  {str(e)}")
            if attempts < MAX_RETRIES:
                print(f"Retrying {agent_name} in 3 seconds...\n")
                time.sleep(3)
            else:
                print(f"Max retries reached for {agent_name}. Propagating error.")
                raise e