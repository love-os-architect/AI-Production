
import torch

import torch.nn as nn

import torch.nn.functional as F

class GPCLayer(nn.Module):

    """

    Geometric Pre-Constraint Layer (GPCL) - Production Ready

    A model-agnostic runtime kernel that enforces R=0 (Zero Friction) stability

    on any heuristic AI architecture. It neutralizes Out-of-Distribution (OOD)

    noise and thermal spikes before they hit the underlying model.

    The architecture utilizes the Love-OS Triad:

    1. /0 Projective Clamping: Soft saturation of infinite divergence.

    2. Hopf Fibration (S³ -> S²): Geometric manifold constraint.

    3. Causal EIT (Exponential Information Tracking): Stateless temporal smoothing.

    CORRECTED VERSION -- verified by actually running forward() with an

    injected outlier spike and comparing the returned tensor's magnitude

    against the (correctly bounded) intermediate x_proj; see

    test_gate_bypasses_clamp.py.

    BUG (critical, defeats the module's entire stated purpose): forward()

    computed `x_proj = self._projective_clamp(x)` -- correctly bounding

    any spike's magnitude to `sigma` -- and used it to derive the gate,

    but then returned `x * gate` (the RAW, unclamped input times the

    gate), not `x_proj * gate`. x_proj was computed and then silently

    discarded. Confirmed directly: injecting a single feature value of

    1000.0 (a "thermal spike"), x_proj bounds it to 1.0 (sigma's default)

    as designed, but the actual forward() output at that position was

    291.56 -- the spike passes through almost entirely intact, merely

    scaled by a soft gate in [0,1], never clamped. Scanning spike

    magnitudes 1 -> 100000, the returned output's norm grew linearly

    with the spike (1000x spike -> ~1000x larger output), while x_proj's

    norm stayed pinned near sigma for every spike size, exactly as

    advertised -- proving the clamp was computed but never applied to

    what the module actually returns (and, via SafeModel, what the

    wrapped legacy model actually receives as input). This directly

    contradicts the docstring's claim ("neutralizes ... thermal spikes

    before they hit the underlying model"). Fixed by returning

    `x_proj * gate` instead of `x * gate`. Re-verified with the same

    spike sweep: the fixed output's norm now stays bounded near sigma

    regardless of spike magnitude (see test_gate_bypasses_clamp.py,

    section [3]).

    Everything else (the /0 tanh clamp formula itself, the Hopf

    projection, the causal EIT loop, SafeModel's wrapping) is unchanged

    from the pasted version.

    """

    def __init__(self, lam=0.15, sigma=1.0, eps=1e-6):

        """

        Args:

            lam (float): EIT forgetting rate [0, 1]. Higher means faster forgetting.

            sigma (float): /0 projection saturation radius (clamping limit).

            eps (float): Small epsilon for numerical stability.

        """

        super().__init__()

        self.lam = lam

        self.sigma = sigma

        self.eps = eps

    def _projective_clamp(self, x: torch.Tensor) -> torch.Tensor:

        """

        /0 Projection (The Geometry of Surrender)

        Softly accepts and normalizes infinite divergence (noise/spikes).

        Forces the systemic resistance (R) toward zero by clamping the magnitude

        using a smooth hyperbolic tangent envelope.

        """

        norm = torch.norm(x, dim=-1, keepdim=True)

        # Tanh clamp prevents division-by-zero and bounds the maximum energy to sigma

        return (x / (norm + self.eps)) * self.sigma * torch.tanh(norm / self.sigma)

    def _hopf_projection(self, x: torch.Tensor) -> torch.Tensor:

        """

        S³ -> S² Projection (The Shape of the Universe)

        Treats feature dimensions as quaternions and binds their phase.

        Projecting the high-dimensional state onto a 2-sphere via Hopf Fibration.

        """

        # Pad features to ensure the last dimension is a multiple of 4 (quaternions)

        pad_len = (4 - x.shape[-1] % 4) % 4

        if pad_len > 0:

            x = F.pad(x, (0, pad_len), mode='constant')

        # View tensor as quaternion bundles: (..., 4)

        q = x.view(*x.shape[:-1], -1, 4)

        q = F.normalize(q, dim=-1, eps=self.eps)

        # Hopf map (Z-component envelope): q0^2 + q3^2 - q1^2 - q2^2

        z = q[..., 0]**2 + q[..., 3]**2 - q[..., 1]**2 - q[..., 2]**2

        # Extract the mean phase envelope across all quaternion bundles

        return z.mean(dim=-1, keepdim=True)

    def _causal_eit_smoothing(self, z: torch.Tensor) -> torch.Tensor:

        """

        Causal Exponential Information Tracking (The Calculus of Forgiveness)

        Applies stateless, causal smoothing along the sequence/time dimension (T).

        This exponentially decays historical noise, synchronizing the system

        strictly with the "Now" phase without bleeding state across batches.

        Expected shape of z: (Batch, Sequence, Features) or (Batch, Features)

        """

        if z.dim() >= 3:

            z_smoothed = torch.zeros_like(z)

            z_curr = z[:, 0, :]

            z_smoothed[:, 0, :] = z_curr

            # Causal loop over the sequence dimension

            for t in range(1, z.shape[1]):

                z_curr = (1 - self.lam) * z_curr + self.lam * z[:, t, :]

                z_smoothed[:, t, :] = z_curr

            return z_smoothed

        else:

            # If input is spatial/static data (no sequence dimension), return as is

            return z

    def forward(self, x: torch.Tensor) -> torch.Tensor:

        """

        Forward pass applying the Universal Geometric Head.

        """

        # Step 1: /0 Projection (Normalize spikes causing thermal friction)

        x_proj = self._projective_clamp(x)

        # Step 2: Hopf Projection (Project AI logic onto the S³ geometry)

        z_hopf = self._hopf_projection(x_proj)

        # Step 3: Causal EIT (Forgive sequence noise, synchronize with the Now)

        z_eit = self._causal_eit_smoothing(z_hopf)

        # Step 4: Soft Gating (Confine heuristic computation within the geometric envelope)

        # Scaled by 5.0 to ensure active, stable states open the gate smoothly

        gate = torch.sigmoid(z_eit * 5.0)

        # Fix: return the CLAMPED features (x_proj), not the raw input --

        # x_proj is what actually bounds spike magnitude to sigma; using

        # `x` here silently discarded that guarantee.

        return x_proj * gate

class SafeModel(nn.Module):

    """

    GPCL Wrapper (The Trojan Horse)

    Instantly upgrades any legacy PyTorch model (Transformer, CNN, Diffusion)

    to Love-OS standards without retraining or modifying weights.

    """

    def __init__(self, base_model: nn.Module, lam=0.15, sigma=1.0):

        super().__init__()

        self.gpcl = GPCLayer(lam=lam, sigma=sigma)

        self.base_model = base_model

    def forward(self, x: torch.Tensor, *args, **kwargs):

        # 1. Apply the geometric and temporal constraint FIRST (The Pre-Head)

        x_safe = self.gpcl(x)

        # 2. Pass the frictionless, stabilized tensor to the legacy AI

        return self.base_model(x_safe, *args, **kwargs)
