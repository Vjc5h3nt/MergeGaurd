FROM public.ecr.aws/lambda/python:3.12

WORKDIR /var/task

# Install build tools for native extensions
RUN dnf install -y gcc gcc-c++ && dnf clean all

# Install uv for fast installs
RUN pip install uv --quiet

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install all dependencies into the Lambda task directory
RUN uv pip install --system \
    "strands-agents>=0.1.0" \
    "boto3>=1.34.0" \
    "tree-sitter>=0.21.0" \
    "tree-sitter-languages>=1.10.0" \
    "unidiff>=0.7.5" \
    "httpx>=0.27.0" \
    "pydantic>=2.7.0" \
    "networkx>=3.3" \
    "pyyaml>=6.0.1" \
    "python-dotenv>=1.0.0" \
    "PyJWT[cryptography]>=2.8.0" \
    --quiet

# Install mergeguard itself
RUN uv pip install --system -e . --no-deps --quiet

CMD ["mergeguard.lambda_handler.handler"]
