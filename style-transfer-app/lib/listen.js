import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

/** All IPv4 LAN addresses of this machine. */
function lanIps() {
  return Object.values(os.networkInterfaces())
    .flat()
    .filter((i) => i && i.family === "IPv4" && !i.internal)
    .map((i) => i.address);
}

/**
 * Use the cert from HTTPS_CERT/HTTPS_KEY if given, otherwise create a
 * self-signed one in ./certs (regenerated when the machine's IPs change).
 */
function loadOrCreateCert(baseDir) {
  if (process.env.HTTPS_CERT && process.env.HTTPS_KEY) {
    return { cert: fs.readFileSync(process.env.HTTPS_CERT), key: fs.readFileSync(process.env.HTTPS_KEY) };
  }
  const dir = path.join(baseDir, "certs");
  const certPath = path.join(dir, "cert.pem");
  const keyPath = path.join(dir, "key.pem");
  const ipsPath = path.join(dir, "ips.txt");
  const ips = lanIps();
  const sanList = ["DNS:localhost", `DNS:${os.hostname()}`, `DNS:${os.hostname()}.local`, "IP:127.0.0.1", ...ips.map((ip) => `IP:${ip}`)];
  const fingerprint = sanList.join(",");

  const stale = !fs.existsSync(certPath) || !fs.existsSync(keyPath) || (fs.existsSync(ipsPath) ? fs.readFileSync(ipsPath, "utf8") : "") !== fingerprint;
  if (stale) {
    fs.mkdirSync(dir, { recursive: true });
    execFileSync("openssl", [
      "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "825",
      "-keyout", keyPath, "-out", certPath,
      "-subj", "/CN=StyleShift",
      "-addext", `subjectAltName=${fingerprint}`,
    ], { stdio: "ignore" });
    fs.chmodSync(keyPath, 0o600);
    fs.writeFileSync(ipsPath, fingerprint);
    console.log("  Created a self-signed HTTPS certificate in ./certs");
  }
  return { cert: fs.readFileSync(certPath), key: fs.readFileSync(keyPath) };
}

export function startServer(app, { port, host, baseDir, https }) {
  const useHttps = /^(1|true|yes|on)$/i.test(process.env.HTTPS || "");
  const scheme = useHttps ? "https" : "http";
  const server = useHttps ? https.createServer(loadOrCreateCert(baseDir), app) : app;

  return new Promise((resolve, reject) => {
    const s = server.listen(port, host, () => {
      const urls = [`${scheme}://localhost:${port}`, ...lanIps().map((ip) => `${scheme}://${ip}:${port}   <- open this on your phone`)];
      resolve({ urls });
    });
    s.on("error", (err) => {
      if (err.code === "EADDRINUSE") {
        console.error(`\n  Port ${port} is already in use. Stop the other app or set a different PORT in .env\n`);
        process.exit(1);
      }
      reject(err);
    });
  });
}
