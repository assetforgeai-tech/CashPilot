# Per-IP device limits: what providers actually document

Research backing `devices_per_ip` in the catalog (CashPilot-4qv), which drives the
egress-conflict warning. Recorded here because the value is only as good as its
source, and a future contributor needs to see the evidence rather than trust a
number someone once typed.

**The rule this table exists to enforce:** write a number only where the provider
states one. Where they do not, leave the key ABSENT â€” the preflight then tells
the user to check the terms, which is honest. A guessed number tells them
something false with full confidence.

Snapshot date: 2026-08-02. These terms change without changelogs; re-check before
relying on any row.

## Documented by the provider

Every row must carry a URL. The one row that did not â€” spide â€” is the row that
was wrong: it was filed under "no number" while the provider's Terms state a
limit of one, in the sentence immediately before the one that was quoted. A
reviewer with a link opens the page and sees it; without one, the error survives.

| Service | devices_per_ip | Kind | Source |
|---|---|---|---|
| honeygain | **1** | hard limit, enforced | Help centre: *"Users may connect 1 device per one IP/Network."* Extra devices trigger a `Network overused` error. <https://support.honeygain.com/hc/en-us/articles/360011188779> |
| iproyal (Pawns.app) | **1** | hard limit, in binding Terms | *"Pawns.app limits the number of devices per single IP address to one (1)."* <https://pawns.app/terms-of-use/> |
| spide | **1** | hard limit, in binding Terms | *"Spide Network limits the number of devices per single IP address to one."* Restrictions also forbid *"connect[ing] more than the allowed number of devices"*. The same paragraph adds that traffic through one IP *"will be distributed between devices utilizing the same IP address"*. <https://spide.network/terms-of-use.html> |
| earnfm | **1** | help-centre guidance, not a Terms clause | *"One Device Per Network: Each device **should** be connected to a unique IP or network."* Phrased as guidance; no device-per-IP clause found in the Terms, so treat enforcement as unproven. <https://help.earn.fm/portal/en/kb/articles/do-i-earn-more-if-i-run-earnfm-on-multiple-devices> |
| ebesucher | **1** | hard limit | Multi-device is allowed only if *"each device ... has to be connected to the Internet through a unique IP address."* <https://www.ebesucher.com/blog/besuchertausch/multigeraete-funktion> |

## Documented as sharing, with no number

These state that devices behind one IP split one allocation. That is real and
worth warning about, but it is not a device count, so the key stays ABSENT and
the effect belongs in `requirements.note`.

| Service | What the provider says |
|---|---|
| storj | Nodes in the same /24 subnet share allocation (already captured in that file's `note`). |

*(spide was listed here in the first draft. That was wrong â€” it belongs in the
table above. Its Terms state a limit of one; the sharing sentence quoted here
sits in the same paragraph as the limit sentence, which was missed.)*

## Not documented anywhere official

`urnetwork`, `packetstream`, `proxyrack`, `repocket`.

Two of these have a number that circulates widely and traces to **no provider
source at all**:

- **repocket â€” "2 devices per IP"**. Repeated across review blogs. Repocket's own
  Terms state only a per-ACCOUNT limit (*"up to five (5) devices ... and a
  maximum of five (5) active sessions"*), which is a different thing.
  <https://repocket.com/terms-and-conditions>
  The catalog declared `devices_per_ip: 2` on that basis; it has been removed.
  Note the honest limit of this conclusion: `help.repocket.com` is a dead host
  and `repocket.com/faq` 404s, so this is *no first-party source found*, which is
  weaker than *no first-party source exists*.
- **proxyrack â€” "2 devices per IP"**. Same pattern; third-party reviews claim
  both 1 and 2 and contradict each other. Proxyrack's two device-limit help
  articles (the newer dated 2026-02-23) mention only a 500-per-account cap.
  Datacentre IPs are accepted at roughly a tenth of the residential rate.
  <https://help.proxyrack.com/en/articles/6532815>


Virtual Machines or Dockers?", updated 2025):

> hosting services is strictly prohibited.**
>
> Prohibited environments: Virtual Machines (VMs) Â· Docker containers Â· Cloud
> hosting services Â· **Personal or home servers** Â· Any device used for business
> or monetization purposes.
>
> environment: your account will be **terminated without prior notice**, any
> **pending payments will be canceled**.

without saying this would make the tool the cause of the ban. It is recorded as
`requirements.container_prohibited: true`, which the preflight reports as its
strongest verdict. The deploy is still allowed â€” informed consent, not a block.

No other catalogued service has been found to name containers this way. The flag
requires a first-party source and must never be inferred from a residential-IP
rule; a test enforces that only sourced services carry it.

## VPS / datacenter acceptance

| Service | Policy |
|---|---|
| honeygain | Datacentre IP types blocked outright ("Unusable network"); VMs discouraged. |
| iproyal (Pawns.app) | Residential only; "does not allow the use of any servers, VPNs, or proxy services". |
| spide | Residential only; servers/VPN/proxy not allowed. |
| ebesucher | "Using the surfbar on a virtual server is not allowed." |
| proxyrack | Allowed, but reclassified to a lower datacentre rate. |
| earnfm | Allowed; datacentre connections are their own uncapped category. |
| repocket | Ambiguous â€” the ToS VPS clause sits in the fraud/offer-abuse section, so whether it covers bandwidth sharing is unclear. Not resolved. |
| urnetwork, packetstream | No statement found either way. |

