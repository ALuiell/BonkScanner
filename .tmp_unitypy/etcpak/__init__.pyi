from typing import Optional

class BC7CompressBlockParams:
    """BC7 compression block parameters.

    Attributes
    ----------
        m_mode_mask: int
            The mode mask.
        m_max_partitions: int
            The maximum partitions.
            m_max_partitions may range from 0 (disables mode 1) to BC7ENC_MAX_PARTITIONS (64).
            The higher this value, the slower the compressor, but the higher the quality.
        m_weights: List[int]
            The weights.
            Relative RGBA or YCbCrA weights.
        m_uber_level: int
            The uber level.
            m_uber_level may range from 0 to BC7ENC_MAX_UBER_LEVEL (4).
            The higher this value, the slower the compressor, but the higher the quality.
        m_perceptual: bool
            Perceptual.
            If m_perceptual is true, colorspace error is computed in YCbCr space, otherwise RGB.
        m_try_least_squares: bool
            Try least squares.
            Set m_try_least_squares to false for slightly faster/lower quality compression.
        m_mode17_partition_estimation_filterbank: bool
            Mode 17 partition estimation filterbank.
            When m_mode17_partition_estimation_filterbank,
            the mode1 partition estimator skips lesser used partition patterns unless they are strongly predicted to be potentially useful.
            There's a slight loss in quality with this enabled (around .08 dB RGB PSNR or .05 dB Y PSNR),
            but up to a 11% gain in speed depending on the other settings.
        m_force_selectors: bool
            Force selectors.
        m_force_alpha: bool
            Force alpha.
        m_quant_mode6_endpoints: bool
            Quant mode 6 endpoints.
        m_bias_mode1_pbits: bool
            Bias mode 1 pbits.
        m_pbit1_weight: float
            Pbit 1 weight.
        m_mode1_error_weight: float
            Mode 1 error weight.
        m_mode5_error_weight: float
            Mode 5 error weight.
        m_mode6_error_weight: float
            Mode 6 error weight.
        m_mode7_error_weight: float
            Mode 7 error weight.
    """

    m_mode_mask: int = 2**32 - 1
    m_max_partitions: int = 64
    m_try_least_squares: bool = True
    m_mode17_partition_estimation_filterbank: bool = True
    m_uber_level: int = 0
    m_force_selectors: bool = False
    m_force_alpha: bool = False
    m_quant_mode6_endpoints: bool = False
    m_bias_mode1_pbits: bool = False
    m_pbit1_weigh: float = 1.0
    m_mode1_error_weight: float = 1.0
    m_mode5_error_weight: float = 1.0
    m_mode6_error_weight: float = 1.0
    m_mode7_error_weight: float = 1.0
    m_perceptual: bool = False
    m_weights: list[int] = [1, 1, 1, 1]

    def __init__(self) -> None: ...
    def init_linear_weights(self) -> None:
        """Initialize the weights for linear mode.

        m_perceptual: false
        m_weights = [1,1,1,1]
        """
        ...
    def init_perceptual_weights(self) -> None:
        """Initialize the weights for perceptual mode.

        m_perceptual: true
        m_weights = [128,64,16,32]
        """

def compress_bc1(data: bytes, width: int, height: int) -> bytes: ...
def compress_bc1_dither(data: bytes, width: int, height: int) -> bytes: ...
def compress_bc3(data: bytes, width: int, height: int) -> bytes: ...
def compress_bc4(data: bytes, width: int, height: int) -> bytes: ...
def compress_bc5(data: bytes, width: int, height: int) -> bytes: ...
def compress_bc7(
    data: bytes, width: int, height: int, params: Optional[BC7CompressBlockParams]
) -> bytes: ...
def compress_etc1_rgb(data: bytes, width: int, height: int) -> bytes: ...
def compress_etc1_rgb_dither(data: bytes, width: int, height: int) -> bytes: ...
def compress_etc2_rgb(data: bytes, width: int, height: int) -> bytes: ...
def compress_etc2_rgba(data: bytes, width: int, height: int) -> bytes: ...
def compress_eac_r(data: bytes, width: int, height: int) -> bytes: ...
def compress_eac_rg(data: bytes, width: int, height: int) -> bytes: ...
def decompress_etc1_rgb(data: bytes, width: int, height: int) -> bytes: ...
def decompress_etc2_rgb(data: bytes, width: int, height: int) -> bytes: ...
def decompress_etc2_rgba(data: bytes, width: int, height: int) -> bytes: ...
def decompress_etc2_r11(data: bytes, width: int, height: int) -> bytes: ...
def decompress_etc2_rg11(data: bytes, width: int, height: int) -> bytes: ...
def decompress_bc1(data: bytes, width: int, height: int) -> bytes: ...
def decompress_bc3(data: bytes, width: int, height: int) -> bytes: ...
def decompress_bc4(data: bytes, width: int, height: int) -> bytes: ...
def decompress_bc5(data: bytes, width: int, height: int) -> bytes: ...
def decompress_bc7(data: bytes, width: int, height: int) -> bytes: ...
