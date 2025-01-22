import subprocess
from secrets import token_hex


def flash(infile: str, ip: str) -> bool:
    """
        infile: path to file to flash
        ip: hostname of server to flash to (eg: ectf@pi.neilhommes.xyz)
        
        returns True if the upload and flash was successful, False otherwise.
    """
    print("Uploading files to ectf server")

    path = f'~/ectf2025/build_out/{token_hex(16)}.bin'
    update_script = '~/ectf2025/CI/update'
    venv = '. ~/ectf2025/.venv/bin/activate'
    try:
        subprocess.run(
            [
                "rsync",
                "--rsh=ssh -o StrictHostKeyChecking=accept-new",
                "-av",
                "--progress",
                "--delete",
                "--ignore-times",
                infile,
                f"{ip}:{path}"
            ],
            check=True,
        )
    except subprocess.SubprocessError:
        print(f"Failed to upload file to {ip}")
        return False

    try:
        subprocess.run(
            [
                "ssh",
                "-o StrictHostKeyChecking=accept-new",
                ip,
                f'{venv} && {update_script} {path} && rm {path}'
            ],
            check=True,
        )
    except subprocess.SubprocessError:
        print(f"Failed to flash on {ip}")
        return False

    return True

def test():
    """
    run test cases... Will implement later when done
    """
    pass

if __name__ == '__main__':
    flash('builds/max78000.bin', 'ectf@pi.neilhommes.xyz')
    test()