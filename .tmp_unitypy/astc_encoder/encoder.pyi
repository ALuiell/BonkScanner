from __future__ import annotations

from typing import Literal, Optional, Union

from .enum import (
    ASTCConfigFlags,
    ASTCProfile,
    ASTCQualityPreset,
    ASTCSwizzleComponentSelector,
    ASTCType,
)

class ASTCImage:
    """
    An uncompressed 2D or 3D image.

    3D image are passed in as an array of 2D slices.
    Each slice has identical size and color format.

    Attributes
    ----------
    dim_x : int
        The X dimension of the image, in texels.
    dim_y : int
        The Y dimension of the image, in texels.
    dim_z : int
        The Z dimension of the image, in texels.
    data_type : ASTCType
        The data type per component.
    """

    dim_x: int
    dim_y: int
    dim_z: int
    data_type: ASTCType
    data: Optional[bytes]

    def __init__(
        self,
        data_type: ASTCType,
        dim_x: int,
        dim_y: int,
        dim_z: int = 1,
        data: Optional[bytes] = None,
    ) -> None: ...

class ASTCConfig:
    """
    The config structure.

    This structure will initially be populated by the init, but power users may modify it afterwards.
    See astcenccli_toplevel_help.cpp for full user documentation of the power-user settings.

    Note for any settings which are associated with a specific color component, the value in the
    config applies to the component that exists after any compression data swizzle is applied.

    Legal block sizes are:
    - 2d
        - 4x4
        - 5x4
        - 5x5
        - 6x5
        - 6x6
        - 8x5
        - 8x6
        - 8x8
        - 10x5
        - 10x6
        - 10x8
        - 10x10
        - 12x10
        - 12x12
    - 3d
        - 3x3x3
        - 4x3x3
        - 4x4x3
        - 4x4x4
        - 5x4x4
        - 5x5x4
        - 5x5x5
        - 6x5x5
        - 6x6x5
        - 6x6x6

    Attributes
    ----------
    profile : ASTCProfile
        The color profile.
    flags : int
        The set of set flags.
    block_x : int
        The ASTC block size X dimension.
    block_y : int
        The ASTC block size Y dimension.
    block_z : int
        The ASTC block size Z dimension.
    cw_r_weight : int
        The red component weight scale for error weighting (-cw).
    cw_g_weight : int
        The green component weight scale for error weighting (-cw).
    cw_b_weight : int
        The blue component weight scale for error weighting (-cw).
    cw_a_weight : int
        The alpha component weight scale for error weighting (-cw).
    a_scale_radius : int
        The radius for any alpha-weight scaling (-a).
        It is recommended that this is set to 1 when using FLG_USE_ALPHA_WEIGHT on a texture that
        will be sampled using linear texture filtering to minimize color bleed out of transparent
        texels that are adjacent to non-transparent texels.
    rgbm_m_scale : int
        The RGBM scale factor for the shared multiplier (-rgbm).
    tune_partition_count_limit : int
        The maximum number of partitions searched (-partitioncountlimit).
        Valid values are between 1 and 4.
    tune_2partition_index_limit : int
        The maximum number of partitions searched (-2partitionindexlimit).
        Valid values are between 1 and 1024.
    tune_3partition_index_limit : int
        The maximum number of partitions searched (-3partitionindexlimit).
        Valid values are between 1 and 1024.
    tune_4partition_index_limit : int
        The maximum number of partitions searched (-4partitionindexlimit).
        Valid values are between 1 and 1024.
    tune_block_mode_limit : int
        The maximum centile for block modes searched (-blockmodelimit).
        Valid values are between 1 and 100.
    tune_refinement_limit : int
        The maximum iterative refinements applied (-refinementlimit).
        Valid values are between 1 and N; there is no technical upper limit
        but little benefit is expected after N=4.
    tune_candidate_limit : int
        The number of trial candidates per mode search (-candidatelimit).
        Valid values are between 1 and TUNE_MAX_TRIAL_CANDIDATES.
    tune_2partitioning_candidate_limit : int
        The number of trial partitionings per search (-2partitioncandidatelimit).
        Valid values are between 1 and TUNE_MAX_PARTITIONING_CANDIDATES.
    tune_3partitioning_candidate_limit : int
        The number of trial partitionings per search (-3partitioncandidatelimit).
        Valid values are between 1 and TUNE_MAX_PARTITIONING_CANDIDATES.
    tune_4partitioning_candidate_limit : int
        The number of trial partitionings per search (-4partitioncandidatelimit).
        Valid values are between 1 and TUNE_MAX_PARTITIONING_CANDIDATES.
    tune_db_limit : float
        The dB threshold for stopping block search (-dblimit).
        This option is ineffective for HDR textures.
    tune_mse_overshoot : float
        The amount of MSE overshoot needed to early-out trials.
        The first early-out is for 1 partition, 1 plane trials, where we try a minimal encode using
        the high probability block modes. This can short-cut compression for simple blocks.
        The second early-out is for refinement trials, where we can exit refinement once quality is
        reached.
    tune_2partition_early_out_limit_factor : float
        The threshold for skipping 3.1/4.1 trials (-2partitionlimitfactor).
        This option is further scaled for normal maps, so it skips less often.
    tune_3partition_early_out_limit_factor : float
        The threshold for skipping 4.1 trials (-3partitionlimitfactor).
        This option is further scaled for normal maps, so it skips less often.
    tune_2plane_early_out_limit_correlation : float
        The threshold for skipping two weight planes (-2planelimitcorrelation).
        This option is ineffective for normal maps.
    tune_search_mode0_enable : float
        The config enable for the mode0 fast-path search.
        If this is set to TUNE_MIN_TEXELS_MODE0 or higher then the early-out fast mode0
        search is enabled. This option is ineffective for 3D block sizes.
    """

    profile: ASTCProfile
    flags: ASTCConfigFlags
    block_x: int
    block_y: int
    block_z: int
    cw_r_weight: int
    cw_g_weight: int
    cw_b_weight: int
    cw_a_weight: int
    a_scale_radius: int
    rgbm_m_scale: int
    tune_partition_count_limit: int
    tune_2partition_index_limit: int
    tune_3partition_index_limit: int
    tune_4partition_index_limit: int
    tune_block_mode_limit: int
    tune_refinement_limit: int
    tune_candidate_limit: int
    tune_2partitioning_candidate_limit: int
    tune_3partitioning_candidate_limit: int
    tune_4partitioning_candidate_limit: int
    tune_db_limit: float
    tune_mse_overshoot: float
    tune_2partition_early_out_limit_factor: float
    tune_3partition_early_out_limit_factor: float
    tune_2plane_early_out_limit_correlation: float
    tune_search_mode0_enable: float
    # progress_callback: Optional[Callable]
    def __init__(
        self,
        profile: ASTCProfile,
        block_x: int,
        block_y: int,
        block_z: int = 1,
        quality: Union[float, ASTCQualityPreset] = ASTCQualityPreset.MEDIUM,
        flags: int = 0,
    ) -> None: ...

class ASTCSwizzle:
    """A texel component swizzle.

    Attributes
    ----------
    r : ASTCSwizzleComponentSelector
        The red component selector.
    g : ASTCSwizzleComponentSelector
        The green component selector.
    b : ASTCSwizzleComponentSelector
        The blue component selector.
    a : ASTCSwizzleComponentSelector
        The alpha component selector.
    """

    r: ASTCSwizzleComponentSelector
    g: ASTCSwizzleComponentSelector
    b: ASTCSwizzleComponentSelector
    a: ASTCSwizzleComponentSelector

    def __init__(
        self,
        r: ASTCSwizzleComponentSelector = ASTCSwizzleComponentSelector.R,
        g: ASTCSwizzleComponentSelector = ASTCSwizzleComponentSelector.G,
        b: ASTCSwizzleComponentSelector = ASTCSwizzleComponentSelector.B,
        a: ASTCSwizzleComponentSelector = ASTCSwizzleComponentSelector.A,
    ) -> None: ...
    @classmethod
    def from_str(cls, swizzle: str) -> ASTCSwizzle:
        """
        Create a swizzle from a string.

        The string must be 4 characters long, with each character being one of:
          - r/R: Red component.
          - g/G: Green component.
          - b/B: Blue component.
          - a/A: Alpha component.
          - 0: always 0
          - 1: always 1
          - z/Z: Reconstructed normal vector Z component.
        """
        ...

class ASTCContext:
    config: ASTCConfig
    threads: int

    def __init__(self, config: ASTCConfig, threads: int = 1) -> None: ...
    def compress(self, image: ASTCImage, swizzle: ASTCSwizzle) -> bytes: ...
    def decompress(
        self, data: bytes, image: ASTCImage, swizzle: ASTCSwizzle
    ) -> ASTCImage: ...

class ASTCError(Exception):
    pass

def compute_error_metrics(
    compute_hdr_metrics: bool,
    compute_hdr_rg_metrics: bool,
    input_components: Literal[0, 1, 2, 3, 4],
    img1: ASTCImage,
    img2: ASTCImage,
    fstop_lo: int,
    fstop_hi: int,
) -> dict:
    """Compute error metrics comparing two images.

    Parameters
    ----------
    compute_hdr_metrics : bool
        True if HDR metrics should be computed.
    compute_normal_metrics: bool
        True if normal map metrics should be computed.
    input_components : Literal[0, 1, 2, 3, 4]
        The number of color components in the input images.
    img1: ASTCImage
        The original image.
    img2: ASTCImage
        The compressed image.
    fstop_lo: int
        The low exposure fstop (HDR only).
    fstop_hi: int
        The high exposure fstop (HDR only).

    Returns
    -------
    dict
        A dictionary with the following keys:
        - "psnr": The peak signal-to-noise ratio.
        - "psnr_rgb": The peak signal-to-noise ratio for RGB channels.
        - "psnr_alpha": The peak signal-to-noise ratio for the alpha channel.
        - "peak_rgb": The peak value for RGB channels.
        - "mspnr_rgb": The mean signal-to-noise ratio for RGB channels. (hdr metric)
        - "log_rgmse_rgb": The log root mean square error for RGB channels. (hdr metric)
        - "mean_angular_errorsum": The mean angular error. (normal map metric)
        - "worst_angular_errorsum": The worst angular error. (normal map metric)

        If a value is -1 it means that this metric was not computed.
    """
    pass

__all__ = (
    "ASTCConfig",
    "ASTCContext",
    "ASTCImage",
    "ASTCSwizzle",
    "ASTCError",
    "compute_error_metrics",
)
