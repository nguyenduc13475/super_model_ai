import torch
from model import Diffusion_Video_Model, show_image

torch.set_printoptions(
    precision = 16,
    sci_mode = False,
    threshold = 100
)

model = Diffusion_Video_Model()
if torch.cuda.is_available():
    model.cuda()

video, debug_information = model.infer([
    "I eat shit",
    "I love you"
], (64, 96), 2)