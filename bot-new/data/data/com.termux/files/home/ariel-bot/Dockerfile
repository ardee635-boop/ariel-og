# Docker runtime for Render — used instead of Render's native Node
# environment specifically because that environment doesn't ship ffmpeg,
# (used for media conversion). This installs ffmpeg at
# the OS level via apt, which the native Node runtime doesn't give us
# access to.
FROM node:20-slim

# ffmpeg: media conversion.
# python3/pip: this repo also runs Python components (Groq/Gemini calls,
# the RPG engine bridge, psycopg2, etc.) alongside the Node process.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Node deps first so this layer is cached unless package.json changes.
COPY package*.json ./
RUN npm install --omit=dev

# Install Python deps the same way — cached unless requirements.txt changes.
COPY requirements.txt ./
RUN pip3 install --break-system-packages -r requirements.txt

# Now copy the rest of the source.
COPY . .

EXPOSE 10000

CMD ["node", "bot/index.js"]
