from quipkey.transcriber import gpu_device


def test_gpu_preferred_when_available():
    assert gpu_device(["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]) == "cuda"
    assert gpu_device(["DmlExecutionProvider", "CPUExecutionProvider"]) == "directml"
    assert gpu_device(["CPUExecutionProvider"]) is None
