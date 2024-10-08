import torch
from torch import nn
from torch import optim
from torch.nn import functional as func
import transformers
import matplotlib.pyplot as plt
import random
import os
import cv2 as cv
import function_low_gpu
import psutil as ps
import numpy as np
import yt_dlp
from datetime import timedelta
from youtubesearchpython import VideosSearch
import re
from random import choices, randint
import string

with open("wordlist.txt") as f:
    word_list = f.readlines()

def random_sentence():
    return ' '.join(map(lambda w : w[0:-1], choices(word_list, k = randint(1, 10))))

torch.set_printoptions(
    precision = 4,
    sci_mode = False,
    threshold = 100
)

def exist_video():
    return os.path.isfile("videos/video0.mp4")

def delete_video():
    for f in os.listdir("videos"):
        os.remove(os.path.join("videos", f))
            

def is_short_video(duration_str, duration_limit):
    parts = list(map(int, duration_str.split(':')))
    if len(parts) == 2:
        duration = timedelta(minutes = parts[0], seconds = parts[1])
    else:
        duration = timedelta(hours = parts[0], minutes = parts[1], seconds = parts[2])

    return duration < timedelta(seconds = duration_limit[1]) and duration > timedelta(seconds = duration_limit[0])

def configuration_at_time_step(time_step):
    if time_step < 1000:
        return ([5, 3 * 60], 64)
    elif time_step < 5000:
        return ([30, 5 * 60], 128)
    elif time_step < 10000:
        return ([60, 6 * 60], 128)
    elif time_step < 20000:
        return ([60, 6 * 60], 64)
    else:
        return ([2 * 60, 6 * 60], 32)

def download_video(time_step, training_phase):
    if not os.path.exists("videos"):
            os.mkdir("videos")

    if training_phase == "Autoencoder":
        for i in range(2):
            while True:
                try:
                    ytd = yt_dlp.YoutubeDL({
                        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                        "outtmpl": "videos/video" + str(i) + ".mp4"
                    })

                    is_search_done = False
                    v_id = None
                    while not is_search_done:
                        for v in VideosSearch(random_sentence(), 5).result()["result"]:
                            if is_short_video(v["duration"], [60, 3 * 60]):
                                is_search_done = True
                                v_id = v["id"]

                    ytd.download(["https://www.youtube.com/watch?v=" + v_id])
                    break
                except:
                    for f in os.listdir("videos"):
                        if f.startswith("video") and re.search(r"video(\d+)\.mp4", f) == None:
                            os.remove(os.path.join("videos", f))

    elif training_phase == "Stable Diffusion":
        duration, _ = configuration_at_time_step(time_step)

        while True:
            try:
                ytd = yt_dlp.YoutubeDL({
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "outtmpl": "videos/video0.mp4"
                })

                is_search_done = False
                v_id = None
                v_description = ""
                while not is_search_done:
                    for v in VideosSearch(random_sentence(), 5).result()["result"]:
                        if is_short_video(v["duration"], duration):
                            is_search_done = True
                            v_id = v["id"]
                            bonus_description = ""
                            if v["descriptionSnippet"] != None:
                                bonus_description = ". "
                                for desc in v["descriptionSnippet"]:
                                    bonus_description += desc["text"]

                            v_description = v["title"] + bonus_description

                ytd.download(["https://www.youtube.com/watch?v=" + v_id])
                with open("videos/description0.txt", "w") as f:
                    f.write(v_description)

                break
            except:
                for f in os.listdir("videos"):
                    if f.startswith("video") and re.search(r"video(\d+)\.mp4", f) == None:
                        os.remove(os.path.join("videos", f))

def exist_model():
    return os.path.isfile("drive/MyDrive/Video AI/model.ckpt")

# shape (số dòng, số cột) trả về => chu kỳ để dòng lặp lại = cycle dòng
def positional_encoder(shape, cycle):
    m = cycle ** (2 / shape[1])
    temp = torch.arange(0, shape[0], dtype = torch.float32).reshape(shape[0], 1) @ \
           (m ** -torch.arange(0, shape[1] // 2)).unsqueeze(0)
    
    return torch.cat((torch.sin(temp), torch.cos(temp)), 1)

def time_encoder(size, time_step):
    m = 2000 ** (2 / size)
    temp = m ** -torch.arange(0, size // 2) * time_step
    return torch.cat((torch.sin(temp), torch.cos(temp)), 0)

def show_image(integer_tensor_image):
    plt.imshow(integer_tensor_image.permute(1, 2, 0))
    plt.axis('off')
    plt.show()

def make_video(batch_video):
    if not os.path.exists("infered_videos"):
        os.mkdir("infered_videos")
    batch_size, _, height, width = batch_video[0].shape
    for i in range(batch_size):
        file_path = os.path.join("infered_videos", "inference_video" + str(i) + ".mp4")
        video_generator = cv.VideoWriter(file_path, 1983148141, 30, (width, height))
        for j in range(len(batch_video)):
            video_generator.write(batch_video[j][i].permute(1, 2, 0).numpy().astype(np.uint8))
        video_generator.release()

def print_memory_information():
    print(
        "Current CPU RAM Usage : " + 
        str(ps.virtual_memory().used / 1024 ** 3) + 
        " / " + 
        str(ps.virtual_memory().total / 1024 ** 3) +
        " GB"
    )
    print(
        "Current GPU RAM Usage : " + 
        str(torch.cuda.memory_allocated(0) / 1024 ** 3) + 
        " / " + 
        str(torch.cuda.get_device_properties(0).total_memory / 1024 ** 3) +
        " GB"
    )

# thay thành false khi infer
is_training = False

def generate_tensor_file_name():
    while True:
        random_string = ''.join(random.choices(string.ascii_letters + string.digits, k = 10))
        
        if random_string not in os.listdir('computational_graph'):
            return random_string

#module.net có thể là module hoặc func
class One_Input_Call(torch.autograd.Function):
    def forward(context, module, input_tensor):
        if is_training:
            context.module = module.net
            context.name = os.path.join("computational_graph", generate_tensor_file_name())
            print("forward : " + context.name[-10:])
            torch.save(input_tensor, context.name)
        print(module.net)
        torch.cuda.empty_cache()
        return module.net(input_tensor)
        
    def backward(context, output_gradient):
        print("backward : " + context.name[-10:])
        print("Current GPU Usage : " + str(torch.cuda.memory_allocated(0) / 1024 ** 3))

        input_tensor = torch.load(context.name, weights_only = True)
        os.remove(context.name)
        with torch.enable_grad():
            output_tensor = context.module(input_tensor)
            output_tensor.backward(output_gradient)

        torch.cuda.empty_cache()
        return None, input_tensor.grad

class Two_Input_Call(torch.autograd.Function):
    def forward(context, module, input_tensor_1, input_tensor_2):
        if is_training:
            context.module = module.net
            context.name_1 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_1, context.name_1)
            context.name_2 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_2, context.name_2)
            print("forward : " + context.name_1[-10:] + " " + context.name_2[-10:])
        print(module.net)
        torch.cuda.empty_cache()
        return module.net(input_tensor_1, input_tensor_2)
        
    def backward(context, output_gradient):
        print("backward : " + context.name_1[-10:] + " " + context.name_2[-10:])
        print("Current GPU Usage : " + str(torch.cuda.memory_allocated(0) / 1024 ** 3))
        input_tensor_1 = torch.load(context.name_1, weights_only = True)
        input_tensor_2 = torch.load(context.name_2, weights_only = True)
        os.remove(context.name_1)
        os.remove(context.name_2)
        with torch.enable_grad():
            output_tensor = context.module(input_tensor_1, input_tensor_2)
            output_tensor.backward(output_gradient)
        torch.cuda.empty_cache()
        return None, input_tensor_1.grad, input_tensor_2.grad

class Three_Input_Call(torch.autograd.Function):
    def forward(context, module, input_tensor_1, input_tensor_2, input_tensor_3):
        if is_training:
            context.module = module.net
            context.name_1 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_1, context.name_1)
            context.name_2 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_2, context.name_2)
            context.name_3 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_3, context.name_3)
            print("forward : " + context.name_1[-10:] + " " + context.name_2[-10:] + " " + context.name_3[-10:])

        print(module.net)
        torch.cuda.empty_cache()
        return module.net(input_tensor_1, input_tensor_2, input_tensor_3)[0]
        
    def backward(context, output_gradient):
        print("backward : " + context.name_1[-10:] + " " + context.name_2[-10:] + " " + context.name_3[-10:])
        print("Current GPU Usage : " + str(torch.cuda.memory_allocated(0) / 1024 ** 3))
        input_tensor_1 = torch.load(context.name_1, weights_only = True)
        input_tensor_2 = torch.load(context.name_2, weights_only = True)
        input_tensor_3 = torch.load(context.name_3, weights_only = True)
        os.remove(context.name_1)
        os.remove(context.name_2)
        os.remove(context.name_3)
        with torch.enable_grad():
            output_tensor = context.module(input_tensor_1, input_tensor_2, input_tensor_3)[0]
            output_tensor.backward(output_gradient)
        torch.cuda.empty_cache()
        return None, input_tensor_1.grad, input_tensor_2.grad, input_tensor_3.grad

class Four_Input_Call(torch.autograd.Function):
    def forward(context, module, input_tensor_1, input_tensor_2, input_tensor_3, input_tensor_4):
        if is_training:
            context.module = module.net
            context.name_1 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_1, context.name_1)
            context.name_2 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_2, context.name_2)
            context.name_3 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_3, context.name_3)
            context.name_4 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_4, context.name_4)
            print(
                "forward : " + 
                context.name_1[-10:] + " " + 
                context.name_2[-10:] + " " + 
                context.name_3[-10:] + " " + 
                context.name_4[-10:]
            )
        print(module.net)
        torch.cuda.empty_cache()
        return module.net(input_tensor_1, input_tensor_2, input_tensor_3, attn_mask = input_tensor_4)[0]
        
    def backward(context, output_gradient):
        print(
            "backward : " + 
            context.name_1[-10:] + " " + 
            context.name_2[-10:] + " " + 
            context.name_3[-10:] + " " + 
            context.name_4[-10:]
        )
        print("Current GPU Usage : " + str(torch.cuda.memory_allocated(0) / 1024 ** 3))
        input_tensor_1 = torch.load(context.name_1, weights_only = True)
        input_tensor_2 = torch.load(context.name_2, weights_only = True)
        input_tensor_3 = torch.load(context.name_3, weights_only = True)
        input_tensor_4 = torch.load(context.name_4, weights_only = True)
        os.remove(context.name_1)
        os.remove(context.name_2)
        os.remove(context.name_3)
        os.remove(context.name_4)
        with torch.enable_grad():
            output_tensor = context.module(input_tensor_1, input_tensor_2, input_tensor_3, attn_mask = input_tensor_4)[0]
            output_tensor.backward(output_gradient)
        torch.cuda.empty_cache()
        return None, input_tensor_1.grad, input_tensor_2.grad, input_tensor_3.grad, input_tensor_4.grad

def one_input_forward(module, x):
    bearer = torch.tensor([], requires_grad = True, device = "cuda" if torch.cuda.is_available() else "cpu")
    bearer.net = module
    return One_Input_Call.apply(bearer, x)

def two_input_forward(module, x, y):
    bearer = torch.tensor([], requires_grad = True, device = "cuda" if torch.cuda.is_available() else "cpu")
    bearer.net = module
    return Two_Input_Call.apply(bearer, x, y)

def three_input_forward(module, x, y, z):
    bearer = torch.tensor([], requires_grad = True, device = "cuda" if torch.cuda.is_available() else "cpu")
    bearer.net = module
    return Three_Input_Call.apply(bearer, x, y, z)

def four_input_forward(module, x, y, z, w):
    bearer = torch.tensor([], requires_grad = True, device = "cuda" if torch.cuda.is_available() else "cpu")
    bearer.net = module
    return Four_Input_Call.apply(bearer, x, y, z, w)

class Modified_Multiply(torch.autograd.Function):
    def forward(context, input_tensor_1, input_tensor_2):
        if is_training:
            context.name_1 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_1, context.name_1)
            context.name_2 = os.path.join("computational_graph", generate_tensor_file_name())
            torch.save(input_tensor_2, context.name_2)
            print("forward : " + context.name_1[-10:] + " " + context.name_2[-10:])
        print("Modified Multiply")
        torch.cuda.empty_cache()
        return input_tensor_1 * input_tensor_2
        
    def backward(context, output_gradient):
        print("backward : " + context.name_1[-10:] + " " + context.name_2[-10:])
        input_tensor_1 = torch.load(context.name_1, weights_only = True)
        input_tensor_2 = torch.load(context.name_2, weights_only = True)
        os.remove(context.name_1)
        os.remove(context.name_2)
        torch.cuda.empty_cache()
        return output_gradient * input_tensor_2, output_gradient * input_tensor_1

class Diffusion_First_Unit(nn.Module):
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels

        self.diffusion_first_unit_layer = nn.ModuleList([
            nn.GroupNorm(32, in_channels),
            nn.Conv2d(in_channels, out_channels, 3, padding = 1),
            nn.Linear(4 * 320, out_channels),
            nn.GroupNorm(32, out_channels),
            nn.Conv2d(out_channels, out_channels, 3, padding = 1),
            nn.Identity() if in_channels == out_channels else nn.Conv2d(in_channels, out_channels, 1)
        ])

    def forward(self, latent, time_encoding):
        residue = latent
        latent = one_input_forward(self.diffusion_first_unit_layer[0], latent)
        latent = one_input_forward(func.silu, latent)
        latent = one_input_forward(self.diffusion_first_unit_layer[1], latent)

        time_encoding = one_input_forward(func.silu, time_encoding)
        latent = latent + \
                 one_input_forward(self.diffusion_first_unit_layer[2], time_encoding).reshape(1, self.out_channels, 1, 1)
        latent = one_input_forward(self.diffusion_first_unit_layer[3], latent)
        latent = one_input_forward(func.silu, latent)
        latent = one_input_forward(self.diffusion_first_unit_layer[4], latent) + \
                 one_input_forward(self.diffusion_first_unit_layer[5], residue)

        return (latent, time_encoding)
        
class Diffusion_Second_Unit(nn.Module):
    def __init__(self, out_channels):
        super().__init__()
        self.out_channels = out_channels

        self.diffusion_second_unit_layer = nn.ModuleList([
            nn.GroupNorm(32, out_channels),
            nn.Conv2d(out_channels, out_channels, 1),
            nn.LayerNorm(out_channels),
            nn.MultiheadAttention(out_channels, 8, batch_first = True),
            nn.LayerNorm(out_channels),
            nn.MultiheadAttention(out_channels, 8, kdim = 768, vdim = 768, batch_first = True),
            nn.LayerNorm(out_channels),
            nn.MultiheadAttention(out_channels, 8, kdim = 64, vdim = 64, batch_first = True),
            nn.LayerNorm(out_channels),
            nn.Linear(out_channels, out_channels * 8),
            nn.Linear(4 * out_channels, out_channels),
            nn.Conv2d(out_channels, out_channels, 1)
        ])

    def forward(self, latent, context, memory_latent):
        residue_long = latent
        latent = one_input_forward(self.diffusion_second_unit_layer[0], latent)
        latent = one_input_forward(self.diffusion_second_unit_layer[1], latent)
        h, w = latent.shape[-2:]
        latent = latent.reshape(-1, h * w, self.out_channels)
        residue_short = latent
        latent = one_input_forward(self.diffusion_second_unit_layer[2], latent)
        latent = three_input_forward(self.diffusion_second_unit_layer[3], latent, latent, latent) + residue_short

        residue_short = latent
        latent = one_input_forward(self.diffusion_second_unit_layer[4], latent)
        latent = three_input_forward(self.diffusion_second_unit_layer[5], latent, context, context) + residue_short

        residue_short = latent
        latent = one_input_forward(self.diffusion_second_unit_layer[6], latent)
        latent = three_input_forward(self.diffusion_second_unit_layer[7], latent, memory_latent, memory_latent) + residue_short

        residue_short = latent
        latent = one_input_forward(self.diffusion_second_unit_layer[8], latent)
        latent, gate = one_input_forward(self.diffusion_second_unit_layer[9], latent).chunk(2, -1)
        latent = Modified_Multiply.apply(latent, one_input_forward(func.gelu, gate))
        latent = one_input_forward(self.diffusion_second_unit_layer[10], latent) + residue_short
        latent = latent.reshape(-1, self.out_channels, h, w)
        latent = one_input_forward(self.diffusion_second_unit_layer[11], latent) + residue_long

        return latent

class Diffusion_Unit(nn.Module):
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels

        self.diffusion_unit_layer = nn.ModuleList([
            Diffusion_First_Unit(in_channels, out_channels),
            Diffusion_Second_Unit(out_channels)
        ])

    def forward(self, latent, time_encoding, context, memory_latent):
        latent, time_encoding = self.diffusion_unit_layer[0](latent, time_encoding)
        return (self.diffusion_unit_layer[1](latent, context, memory_latent), time_encoding)

class Decoder_Unit(nn.Module):
    def __init__(self, in_channels, out_channels):
        super().__init__()

        self.decoder_unit_layer = nn.ModuleList([
            nn.GroupNorm(32, in_channels),
            nn.Conv2d(in_channels, out_channels, 3, padding = 1),
            nn.GroupNorm(32, out_channels),
            nn.Conv2d(out_channels, out_channels, 3, padding = 1),
            nn.Identity() if in_channels == out_channels else nn.Conv2d(in_channels, out_channels, 1)
        ])

    def forward(self, latent):
        residue = latent
        latent = one_input_forward(self.decoder_unit_layer[0], latent)
        latent = one_input_forward(func.silu, latent)
        latent = one_input_forward(self.decoder_unit_layer[1], latent)
        latent = one_input_forward(self.decoder_unit_layer[2], latent)
        latent = one_input_forward(func.silu, latent)
        latent = one_input_forward(self.decoder_unit_layer[3], latent)
        latent = latent + one_input_forward(self.decoder_unit_layer[4], residue)

        return latent

class Token_Processing_Unit(nn.Module):
    def __init__(self, embed_dim, n_head):
        super().__init__()

        self.token_processing_unit_layer = nn.ModuleList([
            nn.LayerNorm(embed_dim),
            nn.MultiheadAttention(embed_dim, n_head, batch_first = True),
            nn.LayerNorm(embed_dim),
            nn.Linear(embed_dim, 4 * embed_dim),
            nn.Linear(4 * embed_dim, embed_dim)
        ])

    def forward(self, x, mask = None):
        residue = x
        x = one_input_forward(self.token_processing_unit_layer[0], x)
        if mask != None:
            x = four_input_forward(self.token_processing_unit_layer[1], x, x, x, mask)
        else: x = three_input_forward(self.token_processing_unit_layer[1], x, x, x)
        x = x + residue
        
        residue = x
        x = one_input_forward(self.token_processing_unit_layer[2], x)
        x = one_input_forward(self.token_processing_unit_layer[3], x)
        x = Modified_Multiply.apply(x, one_input_forward(func.sigmoid, 1.702 * x))
        return one_input_forward(self.token_processing_unit_layer[4], x) + residue

class VAE_Unit(nn.Module):
    def __init__(self, in_channels, out_channels):
        super().__init__()

        self.VAE_unit_layer = nn.ModuleList([
            nn.GroupNorm(32, in_channels),
            nn.Conv2d(in_channels, out_channels, 3, padding = 1),
            nn.GroupNorm(32, out_channels),
            nn.Conv2d(out_channels, out_channels, 3, padding = 1),
            nn.Identity() if in_channels == out_channels else nn.Conv2d(in_channels, out_channels, 1)
        ])

    def forward(self, x):
        residue = x
        x = one_input_forward(self.VAE_unit_layer[0], (x))
        x = one_input_forward(func.silu, x)
        x = one_input_forward(self.VAE_unit_layer[1], x)
        x = one_input_forward(self.VAE_unit_layer[2], x)
        x = one_input_forward(func.silu, x)
        x = one_input_forward(self.VAE_unit_layer[3], x)
        residue = one_input_forward(self.VAE_unit_layer[4], residue)
        return x + residue
        
class VAE(nn.Module):
    def __init__(self):
        super().__init__()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        self.VAE_layer = nn.ModuleList([
            nn.Conv2d(3, 128, 3, padding = 1),
            VAE_Unit(128, 128),
            VAE_Unit(128, 128),
            nn.Conv2d(128, 128, 3, 2),
            VAE_Unit(128, 256),
            VAE_Unit(256, 256),
            nn.Conv2d(256, 256, 3, 2),
            VAE_Unit(256, 512),
            VAE_Unit(512, 512),
            nn.Conv2d(512, 512, 3, 2),
            VAE_Unit(512, 512),
            VAE_Unit(512, 512),
            VAE_Unit(512, 512),
            nn.GroupNorm(32, 512),
            nn.MultiheadAttention(512, 1, batch_first = True),
            VAE_Unit(512, 512),
            nn.GroupNorm(32, 512),
            nn.Conv2d(512, 32, 3, padding = 1),
            nn.Conv2d(32, 32, 1),
        ])

    def forward(self, x):
        for i in range(3):
            x = one_input_forward(self.VAE_layer[i * 3], x)
            x = self.VAE_layer[i * 3 + 1](x)
            x = self.VAE_layer[i * 3 + 2](x)
            x = func.pad(x, [0, 1, 0, 1])

        x = one_input_forward(self.VAE_layer[9], x)
        x = self.VAE_layer[10](x)
        x = self.VAE_layer[11](x)
        x = self.VAE_layer[12](x)

        residue = x
        x = one_input_forward(self.VAE_layer[13], x)
        h, w = x.shape[-2:]
        x = x.reshape(-1, h * w, 512)

        x = three_input_forward(self.VAE_layer[14], x, x, x)
        x = x.reshape(-1, 512, h, w) + residue


        x = self.VAE_layer[15](x)
        x = one_input_forward(self.VAE_layer[16], x)
        x = one_input_forward(func.silu, x)
        x = one_input_forward(self.VAE_layer[17], x)
        x = one_input_forward(self.VAE_layer[18], x)

        mean_tensor, log_variance_tensor = x.chunk(2, 1)
        std_tensor = log_variance_tensor.clamp(-30, 20).exp() ** 0.5

        return mean_tensor + std_tensor * torch.randn(mean_tensor.shape, device = self.device)
        
class Diffusion_Video_Model(nn.Module):
    def __init__(self):
        super().__init__()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.text_embedding_layer = nn.Embedding(50000, 768)

        self.text_processing_layer = nn.ModuleList(
            [Token_Processing_Unit(768, 12) for _ in range(12)] + [nn.LayerNorm(768)]
        )

        self.memory_latent_processing_layer = nn.ModuleList(
            [Token_Processing_Unit(64, 1) for _ in range(12)] + [nn.LayerNorm(64)]
        )

        self.a = torch.linspace(0.99, 0.97, 1000, device = self.device) ** 2
        self.A = self.a.cumprod(0)

        self.forward_diffusion_layer = nn.ModuleList([
            nn.Linear(320, 4 * 320),
            nn.Linear(4 * 320, 4 * 320),
            nn.Conv2d(16, 320, 3, padding = 1),
            Diffusion_Unit(320, 320),
            Diffusion_Unit(320, 320),
            nn.Conv2d(320, 320, 3, 2, 1),
            Diffusion_Unit(320, 640),
            Diffusion_Unit(640, 640),
            nn.Conv2d(640, 640, 3, 2, 1),
            Diffusion_Unit(640, 1280),
            Diffusion_Unit(1280, 1280),
            nn.Conv2d(1280, 1280, 3, 2, 1),
            Diffusion_First_Unit(1280, 1280),
            Diffusion_First_Unit(1280, 1280),
            Diffusion_Unit(1280, 1280),
            Diffusion_First_Unit(1280, 1280),
            Diffusion_First_Unit(2560, 1280),
            Diffusion_First_Unit(2560, 1280),
            Diffusion_First_Unit(2560, 1280),
            nn.Upsample(scale_factor = 2),
            nn.Conv2d(1280, 1280, 3, padding = 1),
            Diffusion_First_Unit(2560, 1280),
            Diffusion_Second_Unit(1280),
            Diffusion_First_Unit(2560, 1280),
            Diffusion_Second_Unit(1280),
            Diffusion_First_Unit(1920, 1280),
            Diffusion_Second_Unit(1280),
            nn.Upsample(scale_factor = 2),
            nn.Conv2d(1280, 1280, 3, padding = 1),
            Diffusion_First_Unit(1920, 640),
            Diffusion_Second_Unit(640),
            Diffusion_First_Unit(1280, 640),
            Diffusion_Second_Unit(640),
            Diffusion_First_Unit(960, 640),
            Diffusion_Second_Unit(640),
            nn.Upsample(scale_factor = 2),
            nn.Conv2d(640, 640, 3, padding = 1),
            Diffusion_First_Unit(960, 320),
            Diffusion_Second_Unit(320),
            Diffusion_First_Unit(640, 320),
            Diffusion_Second_Unit(320),
            Diffusion_First_Unit(640, 320),
            Diffusion_Second_Unit(320),
            nn.GroupNorm(32, 320),
            nn.Conv2d(320, 16, 3, padding = 1),
        ])

        self.decode_layer = nn.ModuleList([
            nn.Conv2d(16, 16, 1),
            nn.Conv2d(16, 512, 3, padding = 1),
            Decoder_Unit(512, 512),
            nn.GroupNorm(32, 512),
            nn.MultiheadAttention(512, 1, batch_first = True),
            Decoder_Unit(512, 512),
            Decoder_Unit(512, 512),
            Decoder_Unit(512, 512),
            Decoder_Unit(512, 512),
            nn.Upsample(scale_factor = 2),
            nn.Conv2d(512, 512, 3, padding = 1),
            Decoder_Unit(512, 512),
            Decoder_Unit(512, 512),
            Decoder_Unit(512, 512),
            nn.Upsample(scale_factor = 2),
            nn.Conv2d(512, 512, 3, padding = 1),
            Decoder_Unit(512, 256),
            Decoder_Unit(256, 256),
            Decoder_Unit(256, 256),
            nn.Upsample(scale_factor = 2),
            nn.Conv2d(256, 256, 3, padding = 1),
            Decoder_Unit(256, 128),
            Decoder_Unit(128, 128),
            Decoder_Unit(128, 128),
            nn.GroupNorm(32, 128),
            nn.Conv2d(128, 3, 3, padding = 1)
        ])

        self.latent_tokenize_layer = nn.Conv1d(1, 64, 4096, 4096)

        self.encode_layer = VAE()

        self.autoencoder_optimizer = optim.Adam(
            list(self.encode_layer.parameters()) + list(self.decode_layer.parameters()),
            1e-4
        )
        self.autoencoder_criterion = nn.MSELoss()
        self.stable_diffusion_optimizer = optim.SGD(
            list(self.text_embedding_layer.parameters()) + 
            list(self.text_processing_layer.parameters()) +
            list(self.forward_diffusion_layer.parameters()) +
            list(self.latent_tokenize_layer.parameters()) +
            list(self.memory_latent_processing_layer.parameters()),
            1e-4
        )
        self.stable_diffusion_criterion = nn.MSELoss()

    def decode(self, latent):
        latent = one_input_forward(self.decode_layer[0], latent)
        latent = one_input_forward(self.decode_layer[1], latent)
        latent = self.decode_layer[2](latent)

        residue = latent
        latent = one_input_forward(self.decode_layer[3], latent)
        h, w = latent.shape[-2:]
        latent = latent.reshape(-1, h * w, 512)
        latent = three_input_forward(self.decode_layer[4], latent, latent, latent)
        latent = latent.reshape(-1, 512, h, w) + residue

        for i in range(5, 25):
            if isinstance(self.decode_layer[i], Decoder_Unit):
                latent = self.decode_layer[i](latent)
            else:
                latent = one_input_forward(self.decode_layer[i], latent)

        latent = one_input_forward(func.silu, latent)
        return one_input_forward(self.decode_layer[25], latent)

    def text_processing(self, text_embedding):
        x = text_embedding
        mask = torch.full((1000, 1000), float('-inf'), device = self.device)
        mask.masked_fill_(torch.ones(1000, 1000, device = self.device).tril(0).bool(), 0)
        
        for i in range(12):
            x = self.text_processing_layer[i](x, mask)

        return one_input_forward(self.text_processing_layer[12], x)
    
    def latent_attention(self, memory_latent):
        x = memory_latent
        
        for i in range(12):
            x = self.memory_latent_processing_layer[i](x)

        return one_input_forward(self.memory_latent_processing_layer[12], x)

    def latent_processing(self, latent, context, time_embedding, memory_latent):
        if (type(memory_latent) == list):
            memory_latent = torch.cat(memory_latent, 1)
        memory_latent = memory_latent + 0.5 * positional_encoder((memory_latent.shape[1], 64), 50000).to(self.device)

        time_encoding = one_input_forward(self.forward_diffusion_layer[0], time_embedding)
        time_encoding = one_input_forward(func.silu, time_encoding)
        time_encoding = one_input_forward(self.forward_diffusion_layer[1], time_encoding)

        memory_latent = self.latent_attention(memory_latent)

        print("Memory Latent Attention done!")
        print("UNET downward...")

        S = []
        for i in range(2, 14):
            if type(self.forward_diffusion_layer[i]) == nn.Conv2d:
                latent = one_input_forward(self.forward_diffusion_layer[i], latent)
            elif type(self.forward_diffusion_layer[i]) == Diffusion_Unit:
                latent, time_encoding = self.forward_diffusion_layer[i](latent, time_encoding, context, memory_latent)
            elif type(self.forward_diffusion_layer[i]) == Diffusion_First_Unit:
                latent, time_encoding = self.forward_diffusion_layer[i](latent, time_encoding)
            S.append(latent)

        print("Inside bottleneck...")
        latent, time_encoding = self.forward_diffusion_layer[14](latent, time_encoding, context, memory_latent)
        latent, time_encoding = self.forward_diffusion_layer[15](latent, time_encoding)

        print("UNET upward...")
        i = 16
        while i <= 42:
            latent = torch.cat((latent, S.pop()), 1)
            latent, time_encoding = self.forward_diffusion_layer[i](latent, time_encoding)
            i += 1

            if i != 17 and i != 18 and i != 19:
                latent = self.forward_diffusion_layer[i](latent, context, memory_latent)
                i += 1

            if i == 19 or i == 27 or i == 35:
                latent = one_input_forward(self.forward_diffusion_layer[i], latent)
                latent = one_input_forward(self.forward_diffusion_layer[i + 1], latent)
                i += 2

        latent = one_input_forward(self.forward_diffusion_layer[43], latent)
        latent = one_input_forward(func.silu, latent)
        predicted_noise = one_input_forward(self.forward_diffusion_layer[44], latent)
        return predicted_noise

    # previous_latent = (23, 16, 64, 96) => (23, 1, 16 * 64 * 96) => (23, 64, 24) => (23, 24, 64)
    def latent_tokenize(self, previous_latent):
        return self.latent_tokenize_layer(previous_latent.reshape(previous_latent.shape[0], 1, -1)).permute(0, 2, 1)

    def infer(self, prompts, latent_shape, frames):
        global is_training
        is_training = False
        batch_size = len(prompts)
        h, w = latent_shape

        video = []
        debug_information = []
        memory_latent = [torch.zeros(batch_size, h * w // 256, 64, device = self.device)]

        BPE_tokenizer = transformers.CLIPTokenizer("vocabulary.json", "merge.txt", clean_up_tokenization_spaces = True)
        token_sentences = torch.tensor(BPE_tokenizer.batch_encode_plus(
            prompts, padding = "max_length", max_length = 1000
        ).input_ids, device = self.device)

        with torch.no_grad():
            text_embedding = self.text_embedding_layer(token_sentences) + 0.5 * positional_encoder((1000, 768), 2000).to(self.device)
            context = self.text_processing(text_embedding)

            print("Context has been calculated, its shape is " + str(context.shape))

            for i in range(frames):
                print("Infer frame " + str(i))

                latent = torch.randn(batch_size, 16, h, w, device = self.device)
                print("Latent has been randomly chosen!")
                print("Started inference loop")

                # change this shit to 0
                for t in range(980, 0, -20):
                    time_embedding = time_encoder(320, t).reshape(1, 320).to(self.device)
                    predicted_noise = self.latent_processing(latent, context, time_embedding, memory_latent)

                    At = self.A[t]
                    At_k = self.A[t - 20]

                    latent = \
                        At_k ** 0.5 * (1 - At / At_k) / (1 - At) * predicted_noise + \
                        (At / At_k) ** 0.5 * (1 - At_k) / (1 - At) * latent + \
                        ((1 - At_k) / (1 - At) * (1 - At / At_k)) ** 0.5 * torch.randn(latent.shape, device = self.device)
                    print("Time step " + str(t) + " has been infered")

                memory_latent.append(self.latent_tokenize(latent))
                video.append(((self.decode(latent) + 1) * 255 / 2).to("cpu", dtype = torch.int32).clamp(0, 255))
                debug_information.append(self.decode(latent))
                print("Inference done!")

        # video là list chứa frame phần tử, mỗi phần tử là 1 batch các frame trên cpu
        return (video, debug_information)
    
    def one_step_train_auto_encoder(self, batch_frames):
        loss = self.autoencoder_criterion(self.decode(self.encode_layer(batch_frames)), batch_frames)
        print("Autoencoder Loss = " + str(loss.item()))

        loss.backward()
        self.autoencoder_optimizer.step()
        self.autoencoder_optimizer.zero_grad()
        print("Autoencoder Stepped")

        return loss.item()


    def one_step_train_stable_diffusion(self, memory_latent, prompt):
        _, frames, _, height, width = memory_latent.shape
        
        random_frame = random.randint(0, frames - 1)
        # (1, 16, 64, 96)
        chosen_latent = memory_latent[:, random_frame]
        print("Chosing latent done, latent shape is " + str(chosen_latent.shape))

        random_time = random.randint(0, 999)
        time_embedding = time_encoder(320, random_time).reshape(1, 320).to(self.device)

        # shape (1, 16, 64, 96)
        added_noise = torch.randn(chosen_latent.shape, device = self.device)
        noise_latent = \
            self.A[random_time] ** 0.5 * chosen_latent + \
            (1 - self.A[random_time]) ** 0.5 * added_noise
        
        print("Add noise done!")
        BPE_tokenizer = transformers.CLIPTokenizer("vocabulary.json", "merge.txt", clean_up_tokenization_spaces = True)
        token_sentences = torch.tensor(BPE_tokenizer.batch_encode_plus(
            prompt, padding = "max_length", max_length = 1000
        ).input_ids, device = self.device)

        # shape (1, 1000, 768)
        context = self.text_processing(
            one_input_forward(self.text_embedding_layer, token_sentences) + 
            0.5 * positional_encoder((1000, 768), 2000).to(self.device)
        )

        print("Text processing done, context tensor shape is " + str(context.shape))

        # (1, 23, 16, 64, 96)
        previous_latent = torch.cat((
            torch.zeros(1, 1, 16, height, width, device = self.device), 
            memory_latent[:, :random_frame]
        ), 1)
        # (23, 24, 64)
        previous_latent = self.latent_tokenize(
            previous_latent.reshape(-1, 16, height, width)
        ).reshape(1, -1, 64)
        torch.cuda.empty_cache()
        print("Previous latent has been calculated, its shape is " + str(previous_latent.shape))
        
        predicted_noise = self.latent_processing(noise_latent, context, time_embedding, previous_latent)
        loss = self.stable_diffusion_criterion(predicted_noise, added_noise)
        print("Stable Diffusion Loss = " + str(loss.item()))

        loss.backward()
        print("Stable Diffusion Backwarded Successfully!")

        self.stable_diffusion_optimizer.step()
        print("Stable Diffusion Stepped")

        self.stable_diffusion_optimizer.zero_grad()
        print("Stable Diffusion Gradient Reset")

        return loss.item()

    def train_auto_encoder(self, time_step, num_epochs):
        global is_training
        is_training = True

        resolution = time_step % 6
        if resolution == 0:
            resolution = [512, 384]
        elif resolution == 1:
            resolution = [768, 512]
        elif resolution == 2:
            resolution = [1024, 640]
        elif resolution == 3:
            resolution = [1408, 896]
        elif resolution == 4:
            resolution = [1664, 1024]
        elif resolution == 5:
            resolution = [1920, 1280]

        batch_video = []
        losses = []

        for f in os.listdir("videos"):
            curent_video = []
            video_generator = cv.VideoCapture(os.path.join("videos", f))
            for _ in range(64):
                curent_video.append(torch.from_numpy(cv.resize(video_generator.read()[1], resolution)).permute(2, 0, 1))
            video_generator.release()
            batch_video.append(torch.stack(curent_video))
  
        # (128, 3, 512, 768)
        batch_video = torch.cat(batch_video).to(self.device) / 255. * 2 - 1

        for i in range(num_epochs):
            random_index = random.randint(0, 31)
            batch_frames = batch_video[random_index * 4:random_index * 4 + 4]
            loss = self.one_step_train_auto_encoder(batch_frames)
            losses.append(loss)
            torch.cuda.empty_cache()
            print_memory_information()
            self.save()

        return sum(losses) / len(losses)
    
    def train_stable_diffusion(self, time_step, num_epochs):
        global is_training
        is_training = True

        _, frames = configuration_at_time_step(time_step)
        resolution = time_step % 6
        if resolution == 0:
            resolution = [512, 384]
        elif resolution == 1:
            resolution = [768, 512]
        elif resolution == 2:
            resolution = [1024, 640]
        elif resolution == 3:
            resolution = [1408, 896]
        elif resolution == 4:
            resolution = [1664, 1024]
        elif resolution == 5:
            resolution = [1920, 1280]

        losses = []
        video = []
        prompt = []
        video_generator = cv.VideoCapture("videos/video0.mp4")
        for _ in range(frames):
            video.append(torch.from_numpy(cv.resize(video_generator.read()[1], resolution)).permute(2, 0, 1))
        video_generator.release()
        # (64, 3, 512, 768)
        video = (torch.stack(video) / 255. * 2 - 1).to(self.device)
        print("Video has been readed!")
        with open("videos/description0.txt") as df:
            prompt.append(df.read())
        print("Prompt has been readed!")

        memory_latent = []
        with torch.no_grad():
            for i in range(frames // 4):
                memory_latent.append(self.encode_layer(video[i:i + 4]))
                print("Encode chunk " + str(i))

        # (1, 64, 16, 64, 96)
        memory_latent = torch.cat(memory_latent).unsqueeze(0)

        torch.cuda.empty_cache()
        print("Encoding done, memory latent shape is : " + str(memory_latent.shape))

        for i in range(num_epochs):
            loss = self.one_step_train_stable_diffusion(memory_latent, prompt)
            losses.append(loss)
            torch.cuda.empty_cache()
            print_memory_information()
            self.save()

        return sum(losses) / len(losses)
    
    def save(self):
        torch.save({
            "params" : self.state_dict(),
            "autoencoder_optimizer": self.autoencoder_optimizer.state_dict(),
            "stable_diffusion_optimizer": self.stable_diffusion_optimizer.state_dict()
        }, "drive/MyDrive/Video AI/model.ckpt")

        print("Model has been saved successfully.")

    def load(self):
        model = torch.load("drive/MyDrive/Video AI/model.ckpt", weights_only = True)
        self.load_state_dict(model["params"])
        self.autoencoder_optimizer.load_state_dict(model["autoencoder_optimizer"])
        self.stable_diffusion_optimizer.load_state_dict(model["stable_diffusion_optimizer"])

        print("Model has been loaded successfully.")

if not os.path.exists("computational_graph"):
    os.mkdir("computational_graph")

model = Diffusion_Video_Model()
if exist_model():
    model.load()

if torch.cuda.is_available():
    model.cuda()
    print("Model has been moved to CUDA!")

print("Started to train autoencoder...")
for time_step in range(1000000):
    if exist_video():
        delete_video()
    download_video(time_step, "Autoencoder")

    loss = model.train_auto_encoder(time_step, 50)
    print("Time step " + str(time_step) + ": Autoencoder Loss = " + str(loss))

print("Started to train stable diffusion...")
for time_step in range(1000000):
    if  exist_video():
        delete_video()
    download_video(time_step, "Stable Diffusion")

    loss = model.train_stable_diffusion(time_step, 50)
    print("Time step " + str(time_step) + ": Stable Diffusion Loss = " + str(loss))

print("Started inference...")

batch_video, _ = model.infer([
    "I eat shit",
    "I eat cock"
], (64, 96), 10)

make_video(batch_video)
show_image(batch_video[0][0])