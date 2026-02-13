
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
    while True:
        try:
            result = callable_fn()
            return result
        except Exception as e:
            print(f"\n[RETRY] {agent_name} failed:")
            print(f"  {str(e)}")
            print(f"Retrying {agent_name}...\n")
            # Loop continues, callable will be re-executed