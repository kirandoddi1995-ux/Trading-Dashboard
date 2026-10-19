FROM python:3.13.9-slim-bookworm@sha256:8cdd496996889eef0a8a7921c152c0a4a9f18a26c7a5e7257d3c90b431891894
WORKDIR /app
ENV ARROW_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
COPY --chmod=0444 requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: --no-deps --require-hashes -r /app/requirements.txt
COPY --chmod=0444 outcomes_private_worker.py archive_catalog_reconcile.py archive_catalog_verify.py archive_recovery_review.py outcomes_footer_diagnostic.py outcomes_large_profile.py /app/
USER 65534:65534
ENTRYPOINT ["python", "-B", "/app/outcomes_private_worker.py"]
