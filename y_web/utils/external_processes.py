"""Compatibility stubs for removed external process orchestration."""


def _disabled(*args, **kwargs):
    return False, "External process management is disabled in this build."


def _disabled_status(*args, **kwargs):
    return {"status": False, "message": "External process management is disabled."}


def _empty_list(*args, **kwargs):
    return []


def stop_all_exps(*args, **kwargs):
    return True


def terminate_process_on_port(*args, **kwargs):
    return False


def terminate_server_process(*args, **kwargs):
    return False


def start_server(*args, **kwargs):
    return _disabled(*args, **kwargs)


def start_server_screen(*args, **kwargs):
    return _disabled(*args, **kwargs)


def start_client(*args, **kwargs):
    return _disabled(*args, **kwargs)


def terminate_client(*args, **kwargs):
    return False


def start_hpc_server(*args, **kwargs):
    return _disabled(*args, **kwargs)


def stop_hpc_server(*args, **kwargs):
    return True, "HPC server control disabled."


def start_hpc_client(*args, **kwargs):
    return _disabled(*args, **kwargs)


def stop_hpc_client(*args, **kwargs):
    return True, "HPC client control disabled."


def get_server_process_status(*args, **kwargs):
    return "stopped"


def get_ollama_models(*args, **kwargs):
    return ["llama3.2", "minicpm-v"]


def get_llm_models(*args, **kwargs):
    return ["llama3.2", "minicpm-v"]


def is_ollama_running(*args, **kwargs):
    return False


def check_ollama_health(*args, **kwargs):
    return _disabled_status(*args, **kwargs)


def check_vllm_health(*args, **kwargs):
    return _disabled_status(*args, **kwargs)
