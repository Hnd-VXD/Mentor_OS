// Signs of harmful programs, for security_investigate (/etc/mentor/SECURITY.md, "A closer look at a flagged program").
// Each is a reason to look closer, never a verdict: an ordinary tool can hold one of these for a good reason.

rule miner
{
    meta: description = "words of a cryptocurrency miner"
    strings:
        $a = "stratum+tcp://" ascii wide nocase
        $b = "stratum+ssl://" ascii wide nocase
        $c = "--donate-level" ascii wide
        $d = "randomx" ascii wide nocase
        $e = "xmrig" ascii wide nocase
        $f = "cryptonight" ascii wide nocase
    condition:
        any of ($a, $b, $c, $e) or ($d and $f)
}

rule browser_secrets
{
    meta: description = "names of the files where browsers keep passwords and cookies"
    strings:
        $a = "Login Data" ascii wide
        $b = "logins.json" ascii wide
        $c = "key4.db" ascii wide
        $d = "cookies.sqlite" ascii wide
        $e = "Local State" ascii wide
        $f = "Network/Cookies" ascii wide
    condition:
        2 of them
}

rule crypto_wallets
{
    meta: description = "names of cryptocurrency wallets"
    strings:
        $a = "wallet.dat" ascii wide
        $b = ".electrum/wallets" ascii wide
        $c = "exodus.wallet" ascii wide nocase
        $d = "nkbihfbeogaeaoehlefnkodbefgpgknn" ascii wide  // MetaMask's extension
        $e = ".ethereum/keystore" ascii wide
    condition:
        any of them
}

rule user_secrets
{
    meta: description = "paths of the user's SSH keys, keyrings or AI keys"
    strings:
        $a = ".ssh/id_" ascii wide
        $b = ".local/share/keyrings" ascii wide
        $c = ".gnupg/private-keys" ascii wide
        $d = ".config/mentor/keys" ascii wide
        $e = ".claude/.credentials.json" ascii wide
        $f = "/etc/shadow" ascii wide
    condition:
        any of them
}

rule reverse_shell
{
    meta: description = "a way to hand a shell to another computer"
    strings:
        $a = /bash -i\s*>&\s*\/dev\/tcp\// ascii
        $b = /nc(at)? .{0,40}-e \/bin\/(ba)?sh/ ascii
        $c = "pty.spawn(" ascii
        $d = /socat .{0,60}exec:/ ascii nocase
    condition:
        any of them
}

rule sends_to_a_chat
{
    meta: description = "the address of a chat service used to carry stolen data away"
    strings:
        $a = "discord.com/api/webhooks/" ascii wide nocase
        $b = "discordapp.com/api/webhooks/" ascii wide nocase
        $c = "api.telegram.org/bot" ascii wide nocase
    condition:
        any of them
}

rule stays_on_the_computer
{
    meta: description = "ways to start by itself or be loaded into every program"
    strings:
        $a = "/etc/ld.so.preload" ascii wide
        $b = ".config/autostart" ascii wide
        $c = ".config/systemd/user" ascii wide
        $d = "crontab -" ascii wide
        $e = "authorized_keys" ascii wide
    condition:
        any of them
}

rule downloads_and_runs
{
    meta: description = "a download piped straight into a shell"
    strings:
        $a = /(curl|wget)[^|\n]{1,200}\|\s*(ba)?sh/ ascii
    condition:
        $a
}

rule packed
{
    meta: description = "packed with UPX, which hides what is inside"
    strings:
        $a = "UPX!" ascii
        $b = "$Info: This file is packed with the UPX" ascii
    condition:
        uint32(0) == 0x464c457f and any of them
}

rule tor
{
    meta: description = "addresses of the hidden Tor network"
    strings:
        $a = /[a-z2-7]{56}\.onion/ ascii wide
    condition:
        $a
}
