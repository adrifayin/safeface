"""Third-party model architectures, re-implemented or vendored with their licences.

- clip_visual.py : OpenAI CLIP Vision Transformer (MIT licence, see header).
- npr_resnet.py  : NPR detector backbone (Tan et al., CVPR 2024), re-implemented.
- shims/         : minimal stand-ins for the two symbols the upstream TruFor code
                   imports from ``timm`` and ``yacs`` (so neither package is needed).
"""
