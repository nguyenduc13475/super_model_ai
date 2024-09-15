from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
import torch
from torch import nn
from torch.nn import functional as func
import transformers
import matplotlib.pyplot as plt

def exist_model_in_drive():
    auth = GoogleAuth()
    drive = GoogleDrive(auth)

    auth.LoadCredentialsFile("drive_token.json")
    if auth.access_token_expired:
        auth.Refresh()

    drive_files = drive.ListFile({
        "q": "'1r_oDc5Wm7rYqAPvcdRWsHKzjphgu__C3' in parents and trashed=false"
    }).GetList()

    for file in drive_files:
        if file["title"] == "model.ckpt": return True
    
    return False

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

class Diffusion_Sub_Unit(nn.Module):
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels

        self.diffusion_unit_layer_1 = nn.ModuleList([
            nn.GroupNorm(32, in_channels),
            nn.Conv2d(in_channels, out_channels, 3, padding = 1),
            nn.Linear(4 * 320, out_channels),
            nn.GroupNorm(32, out_channels),
            nn.Conv2d(out_channels, out_channels, 3, padding = 1),
            nn.Identity() if in_channels == out_channels else nn.Conv2d(in_channels, out_channels, 1)
        ])

    def forward(self, latent, time_encoding):
        residue = latent
        latent = self.diffusion_unit_layer_1[0](latent)
        latent = func.silu(latent)
        latent = self.diffusion_unit_layer_1[1](latent)

        time_encoding = func.silu(time_encoding)
        latent = latent + self.diffusion_unit_layer_1[2](time_encoding).reshape(1, self.out_channels, 1, 1)
        latent = self.diffusion_unit_layer_1[3](latent)
        latent = func.silu(latent)
        latent = self.diffusion_unit_layer_1[4](latent) + self.diffusion_unit_layer_1[5](residue)

        return (latent, time_encoding)

class Diffusion_Sub_Unit_2(nn.Module):
    def __init__(self, out_channels):
        super().__init__()
        self.out_channels = out_channels

        self.diffusion_unit_layer_2 = nn.ModuleList([
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

    def forward(self, latent, context_tensor, memory_latent):
        residue_long = latent
        latent = self.diffusion_unit_layer_2[0](latent)
        latent = self.diffusion_unit_layer_2[1](latent)
        h, w = latent.shape[-2:]
        latent = latent.reshape(-1, h * w, self.out_channels)
        residue_short = latent
        latent = self.diffusion_unit_layer_2[2](latent)
        latent = self.diffusion_unit_layer_2[3](latent, latent, latent)[0] + residue_short

        residue_short = latent
        latent = self.diffusion_unit_layer_2[4](latent)
        latent = self.diffusion_unit_layer_2[5](latent, context_tensor, context_tensor)[0] + residue_short

        residue_short = latent
        latent = self.diffusion_unit_layer_2[6](latent)
        latent = self.diffusion_unit_layer_2[7](latent, memory_latent, memory_latent)[0] + residue_short

        residue_short = latent
        latent = self.diffusion_unit_layer_2[8](latent)
        latent, gate = self.diffusion_unit_layer_2[9](latent).chunk(2, -1)
        latent = latent * func.gelu(gate)
        latent = self.diffusion_unit_layer_2[10](latent) + residue_short
        latent = latent.reshape(-1, self.out_channels, h, w)
        latent = self.diffusion_unit_layer_2[11](latent) + residue_long

        return latent

class Diffusion_Unit(nn.Module):
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels

        self.diffusion_unit_layer = nn.ModuleList([
            Diffusion_Sub_Unit(in_channels, out_channels),
            Diffusion_Sub_Unit_2(out_channels)
        ])

    def forward(self, latent, time_encoding, context_tensor, memory_latent):
        latent, time_encoding = self.diffusion_unit_layer[0](latent, time_encoding)
        return (self.diffusion_unit_layer[1](latent, context_tensor, memory_latent), time_encoding)

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
        latent = self.decoder_unit_layer[0](latent)
        latent = func.silu(latent)
        latent = self.decoder_unit_layer[1](latent)
        latent = self.decoder_unit_layer[2](latent)
        latent = func.silu(latent)

        return self.decoder_unit_layer[3](latent) + self.decoder_unit_layer[4](residue)

class Text_Processing_Unit(nn.Module):
    def __init__(self, embed_dim, n_head):
        super().__init__()

        self.text_unit_layer = nn.ModuleList([
            nn.LayerNorm(embed_dim),
            nn.MultiheadAttention(embed_dim, n_head, batch_first = True),
            nn.LayerNorm(embed_dim),
            nn.Linear(embed_dim, 4 * embed_dim),
            nn.Linear(4 * embed_dim, embed_dim)
        ])

    def forward(self, x, mask = None):
        residue = x
        x = self.text_unit_layer[0](x)
        x, _ = self.text_unit_layer[1](x, x, x, attn_mask = mask)
        x = x + residue
        
        residue = x
        x = self.text_unit_layer[2](x)
        x = self.text_unit_layer[3](x)
        x = x * func.sigmoid(1.702 * x)
        return self.text_unit_layer[4](x) + residue

class Diffusion_Video_Model(nn.Module):
    def __init__(self):
        super().__init__()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.embedding = nn.Embedding(50000, 768)

        self.text_processing_layer = nn.ModuleList(
            [Text_Processing_Unit(768, 12) for _ in range(12)] + [nn.LayerNorm(768)]
        )

        self.memory_latent_processing_layer = nn.ModuleList(
            [Text_Processing_Unit(64, 1) for _ in range(12)] + [nn.LayerNorm(64)]
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
            Diffusion_Sub_Unit(1280, 1280),
            Diffusion_Sub_Unit(1280, 1280),
            Diffusion_Unit(1280, 1280),
            Diffusion_Sub_Unit(1280, 1280),
            Diffusion_Sub_Unit(2560, 1280),
            Diffusion_Sub_Unit(2560, 1280),
            Diffusion_Sub_Unit(2560, 1280),
            nn.Upsample(scale_factor = 2),
            nn.Conv2d(1280, 1280, 3, padding = 1),
            Diffusion_Sub_Unit(2560, 1280),
            Diffusion_Sub_Unit_2(1280),
            Diffusion_Sub_Unit(2560, 1280),
            Diffusion_Sub_Unit_2(1280),
            Diffusion_Sub_Unit(1920, 1280),
            Diffusion_Sub_Unit_2(1280),
            nn.Upsample(scale_factor = 2),
            nn.Conv2d(1280, 1280, 3, padding = 1),
            Diffusion_Sub_Unit(1920, 640),
            Diffusion_Sub_Unit_2(640),
            Diffusion_Sub_Unit(1280, 640),
            Diffusion_Sub_Unit_2(640),
            Diffusion_Sub_Unit(960, 640),
            Diffusion_Sub_Unit_2(640),
            nn.Upsample(scale_factor = 2),
            nn.Conv2d(640, 640, 3, padding = 1),
            Diffusion_Sub_Unit(960, 320),
            Diffusion_Sub_Unit_2(320),
            Diffusion_Sub_Unit(640, 320),
            Diffusion_Sub_Unit_2(320),
            Diffusion_Sub_Unit(640, 320),
            Diffusion_Sub_Unit_2(320),
            nn.GroupNorm(32, 320),
            nn.Conv2d(320, 16, 3, padding = 1),
        ])

        self.decoder = nn.ModuleList([
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

        self.latent_tokenizer = nn.Conv1d(1, 64, 4096, 4096)

    def decode(self, latent):
        latent = latent / 0.18215

        for i in range(3):
            latent = self.decoder[i](latent)

        residue = latent
        latent = self.decoder[3](latent)
        h, w = latent.shape[-2:]
        latent = latent.reshape(-1, h * w, 512)
        latent, _ = self.decoder[4](latent, latent, latent)
        latent = latent.reshape(-1, 512, h, w) + residue

        for i in range(5, 25):
            latent = self.decoder[i](latent)

        latent = func.silu(latent)
        return self.decoder[25](latent)

    def prompt_attention(self, token_embedding):
        x = token_embedding
        mask = torch.full((1000, 1000), float('-inf'), device = self.device)
        mask.masked_fill_(torch.ones(1000, 1000, device = self.device).tril(0).bool(), 0)
        
        for i in range(12):
            x = self.text_processing_layer[i](x, mask)

        return self.text_processing_layer[12](x)
    
    def latent_attention(self, memory_latent):
        x = memory_latent
        
        for i in range(12):
            x = self.memory_latent_processing_layer[i](x)

        return self.memory_latent_processing_layer[12](x)

    def latent_processing(self, latent, context_tensor, time_embedding, latest_latents):
        memory_latent = torch.cat(latest_latents, 1)
        memory_latent += positional_encoder((memory_latent.shape[1], 64), 50000).to(self.device)

        time_encoding = self.forward_diffusion_layer[0](time_embedding)
        time_encoding = func.silu(time_encoding)
        time_encoding = self.forward_diffusion_layer[1](time_encoding)

        memory_latent = self.latent_attention(memory_latent)

        S = []
        for i in range(2, 14):
            if type(self.forward_diffusion_layer[i]) == nn.Conv2d:
                latent = self.forward_diffusion_layer[i](latent)
            elif type(self.forward_diffusion_layer[i]) == Diffusion_Unit:
                latent, time_encoding = self.forward_diffusion_layer[i](latent, time_encoding, context_tensor, memory_latent)
            elif type(self.forward_diffusion_layer[i]) == Diffusion_Sub_Unit:
                latent, time_encoding = self.forward_diffusion_layer[i](latent, time_encoding)
            else:
                latent = self.forward_diffusion_layer[i](latent, context_tensor, memory_latent)
            S.append(latent)

        latent, time_encoding = self.forward_diffusion_layer[14](latent, time_encoding, context_tensor, memory_latent)
        latent, time_encoding = self.forward_diffusion_layer[15](latent, time_encoding)

        i = 16
        while i <= 42:
            latent = torch.cat((latent, S.pop()), 1)
            latent, time_encoding = self.forward_diffusion_layer[i](latent, time_encoding)
            i += 1

            if i != 17 and i != 18 and i != 19:
                latent = self.forward_diffusion_layer[i](latent, context_tensor, memory_latent)
                i += 1

            if i == 19 or i == 27 or i == 35:
                latent = self.forward_diffusion_layer[i](latent)
                latent = self.forward_diffusion_layer[i + 1](latent)
                i += 2

        latent = self.forward_diffusion_layer[43](latent)
        latent = func.silu(latent)
        model_output = self.forward_diffusion_layer[44](latent)
        return model_output

    def latent_tokenize(self, latent):
        return self.latent_tokenizer(latent.reshape(latent.shape[0], 1, -1)).permute(0, 2, 1)

    def infer(self, batch_input_text, latent_shape, num_frames):
        batch_size = len(batch_input_text)
        h, w = latent_shape

        video = []
        latent_tokens = [torch.zeros(batch_size, h * w // 256, 64, device = self.device)]

        BPE_tokenizer = transformers.CLIPTokenizer("vocabulary.json", "merge.txt", clean_up_tokenization_spaces = True)
        batch_token_sentence = torch.tensor(BPE_tokenizer.batch_encode_plus(
            batch_input_text, padding = "max_length", max_length = 1000
        ).input_ids, device = self.device)

        with torch.no_grad():
            token_embedding = self.embedding(batch_token_sentence) + positional_encoder((1000, 768), 2000).to(self.device)
            context_tensor = self.prompt_attention(token_embedding)

            for _ in range(num_frames):
                latent = torch.randn(batch_size, 16, h, w, device = self.device)

                for t in range(980, -20, -20):
                    time_embedding = time_encoder(320, t).reshape(1, 320).to(self.device)
                    model_output = self.latent_processing(latent, context_tensor, time_embedding, latent_tokens)

                    At = self.A[t]
                    At_k = self.A[t - 20]

                    latent = \
                        At_k ** 0.5 * (1 - At / At_k) / (1 - At) * model_output + \
                        (At / At_k) ** 0.5 * (1 - At_k) / (1 - At) * latent + \
                        ((1 - At_k) / (1 - At) * (1 - At / At_k)) ** 0.5 * torch.randn(latent.shape, device = self.device)
                
                latent_tokens.append(self.latent_tokenize(latent))
                video.append(((self.decode(latent) + 1) * 255 / 2).to("cpu", dtype = torch.int32).clamp(0, 255))

        return video