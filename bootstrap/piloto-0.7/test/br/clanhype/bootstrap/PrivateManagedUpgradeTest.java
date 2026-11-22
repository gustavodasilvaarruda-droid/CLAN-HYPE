package br.clanhype.bootstrap;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.Signature;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Run ONLY against disposable directories and a locally supplied real protected Pokédex. */
public final class PrivateManagedUpgradeTest {
    static int checks;
    private static void ok(boolean value, String label) {
        if (!value) throw new AssertionError(label); checks++;
    }
    interface Work { void run() throws Exception; }
    private static void denies(Work action, String label) throws Exception {
        try { action.run(); } catch (SecurityException expected) { checks++; return; }
        throw new AssertionError("Did not deny: " + label);
    }
    static String sha(byte[] bytes) throws Exception {
        var sb=new StringBuilder();
        for(byte b: MessageDigest.getInstance("SHA-256").digest(bytes))
            sb.append(String.format("%02x",b&255));
        return sb.toString();
    }
    static byte[] oldJar() throws Exception {
        var bytes=new ByteArrayOutputStream();
        try(var z=new ZipOutputStream(bytes)) {
            z.putNextEntry(new ZipEntry("fabric.mod.json"));
            z.write("{\"schemaVersion\":1,\"id\":\"hype_pokedex\",\"version\":\"1.0-test\"}".getBytes(StandardCharsets.UTF_8));
            z.closeEntry();
            z.putNextEntry(new ZipEntry("Classes.bin"));
            var payload=new byte[10000];
            for(int i=0;i<payload.length;i++)payload[i]=(byte)(i*77+(i>>>3));
            z.write(payload);z.closeEntry();
        }
        return bytes.toByteArray();
    }
    static String manifest(KeyPair key, String version, String sha, int size) throws Exception {
        String url=PrivateModUpdater.API+"/mods/hype_pokedex/"+sha+".jar";
        var m=Map.of("release","1","version",version,"url",url,"sha256",sha,
                     "size",Integer.toString(size),"minecraft","1.21.1",
                     "mod_id","hype_pokedex","channel","stable");
        var b=new StringBuilder();
        for(var f:PrivateModUpdater.FIELDS)b.append(f).append('=').append(m.get(f)).append('\n');
        var s=Signature.getInstance("Ed25519");s.initSign(key.getPrivate());
        s.update(b.toString().getBytes(StandardCharsets.US_ASCII));
        return b+"signature="+Base64.getEncoder().encodeToString(s.sign())+"\n";
    }
    record Env(Path root,PrivateModUpdater.Release old,PrivateModUpdater.Release next) {}
    static Env setup(byte[] oldJar,byte[] real,KeyPair key) throws Exception {
        var root=Files.createTempDirectory("hype-managed-upgrade-");
        Files.createDirectory(root.resolve("config"));
        Files.writeString(root.resolve("config/hype-bootstrap.properties"),"update_mode=after_exit\n");
        var stage=Files.createDirectory(root.resolve(".hype-private-staging"));
        String firstSha=sha(oldJar), nextSha=sha(real);
        var before=new PrivateModUpdater.Release("hype_pokedex","1.0-test",firstSha,oldJar.length,1,
              PrivateModUpdater.API+"/mods/hype_pokedex/"+firstSha+".jar",manifest(key,"1.0-test",firstSha,oldJar.length));
        var after=new PrivateModUpdater.Release("hype_pokedex", "2.0.0-beta.8-defesas-multiplas-colecao-compacta-20261109",
              nextSha, real.length,1,PrivateModUpdater.API+"/mods/hype_pokedex/"+nextSha+".jar",
              manifest(key,"2.0.0-beta.8-defesas-multiplas-colecao-compacta-20261109",nextSha,real.length));
        Files.write(stage.resolve("hype_pokedex-"+firstSha+".jar"),oldJar);
        Files.write(stage.resolve("hype_pokedex-"+nextSha+".jar"),real);
        ok(PrivateFirstInstallTransaction.apply(root,before,key.getPublic(),()->true,()->true,()->{}) ==
           PrivateFirstInstallTransaction.Outcome.INSTALLED,"setup owned first mod");
        return new Env(root,before,after);
    }
    static Path file(Env e,PrivateModUpdater.Release r) {return e.root.resolve("mods/hype-hype_pokedex-"+r.sha256()+".jar");}
    static Path marker(Env e) {return e.root.resolve(".hype-private-managed/hype_pokedex.state");}
    public static void main(String[] args) throws Exception {
        if(args.length!=1)throw new IllegalArgumentException("Usage: Test protected-pokedex.jar");
        byte[] real=Files.readAllBytes(Path.of(args[0])), old=oldJar();
        ok(sha(real).equals("176819c73facf52da2826ba3ac1d179926670d64f10c6e92923ccefa65f5ca18"),"correct protected artifact");
        ok(old.length>=1000,"test first JAR is valid sized");
        KeyPair key=KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        Env e=setup(old,real,key);
        denies(()->PrivateManagedUpgrade.upgrade(e.root,e.next,key.getPublic(),()->false,()->true,()->{}),"game running");
        denies(()->PrivateManagedUpgrade.upgrade(e.root,e.next,key.getPublic(),()->true,()->false,()->{}),"not authorized");
        ok(Files.exists(file(e,e.old)),"unsafe calls left old installed");
        ok(PrivateManagedUpgrade.upgrade(e.root,e.next,key.getPublic(),()->true,()->true,()->{})==
           PrivateManagedUpgrade.Outcome.UPDATED,"owned JAR upgraded");
        ok(Files.exists(file(e,e.next))&&!Files.exists(file(e,e.old)),"old removed and new present");
        ok(sha(Files.readAllBytes(file(e,e.next))).equals(e.next.sha256()),"new installed SHA exact");
        ok(Files.exists(e.root.resolve(".hype-private-backups/hype-hype_pokedex-"+e.old.sha256()+".jar")),"old backup retained");
        ok(Files.readString(marker(e)).contains("sha256="+e.next.sha256()),"owned state updated");
        ok(!Files.exists(e.root.resolve(".hype-private-managed/hype_pokedex.pending")),"pending journal removed on success");
        ok(PrivateManagedUpgrade.upgrade(e.root,e.next,key.getPublic(),()->true,()->true,()->{})==
            PrivateManagedUpgrade.Outcome.ALREADY_INSTALLED,"idempotent same release");
        Env fault=setup(old,real,key);
        try {
            PrivateManagedUpgrade.upgrade(fault.root,fault.next,key.getPublic(),()->true,()->true,
                ()->{ throw new IllegalStateException("simulated failed install"); });
            throw new AssertionError("missed injected failure");
        } catch(IllegalStateException expected) {checks++;}
        ok(Files.exists(file(fault,fault.old)),"rollback kept old JAR");
        ok(!Files.exists(file(fault,fault.next)),"rollback removed new JAR");
        ok(Files.readString(marker(fault)).contains(fault.old.sha256()),"rollback retained original marker");
        ok(!Files.exists(fault.root.resolve(".hype-private-managed/hype_pokedex.pending")),"rollback removed journal");
        Env revoke=setup(old,real,key);var allowed=new AtomicBoolean(true);
        denies(()->PrivateManagedUpgrade.upgrade(revoke.root,revoke.next,key.getPublic(),()->true,allowed::get,
                ()->allowed.set(false)),"revoked during upgrade");
        ok(Files.exists(file(revoke,revoke.old))&&!Files.exists(file(revoke,revoke.next)),"revocation rolled back");
        Env tamper=setup(old,real,key);
        Files.writeString(file(tamper,tamper.old),"tampered original");
        denies(()->PrivateManagedUpgrade.upgrade(tamper.root,tamper.next,key.getPublic(),()->true,()->true,()->{}),"modified previous JAR");
        Env duplicate=setup(old,real,key);
        Files.copy(file(duplicate,duplicate.old),duplicate.root.resolve("mods/manual-pokedex.jar"));
        denies(()->PrivateManagedUpgrade.upgrade(duplicate.root,duplicate.next,key.getPublic(),()->true,()->true,()->{}),"duplicate same mod ID");
        Env unowned=setup(old,real,key);
        Files.delete(marker(unowned));
        denies(()->PrivateManagedUpgrade.upgrade(unowned.root,unowned.next,key.getPublic(),()->true,()->true,()->{}),"missing ownership marker");
        Env pending=setup(old,real,key);
        Files.writeString(pending.root.resolve(".hype-private-managed/hype_pokedex.pending"),"manual recovery needed");
        denies(()->PrivateManagedUpgrade.upgrade(pending.root,pending.next,key.getPublic(),()->true,()->true,()->{}),"unfinished journal");
        ok(Files.exists(file(pending,pending.old)),"unfinished journal preserved old JAR");
        Env interrupted=setup(old,real,key);
        Path interruptedNew=file(interrupted,interrupted.next);
        Path interruptedBackup=interrupted.root.resolve(".hype-private-backups/hype-hype_pokedex-" +
                                                       interrupted.old.sha256()+".jar");
        Files.createDirectory(interrupted.root.resolve(".hype-private-backups"));
        Files.copy(file(interrupted,interrupted.old),interruptedBackup);
        Files.writeString(interrupted.root.resolve(".hype-private-managed/hype_pokedex.pending"),
                          "old="+interrupted.old.sha256()+"\nnew="+interrupted.next.sha256()+"\n");
        Files.createLink(interruptedNew,
            interrupted.root.resolve(".hype-private-staging/hype_pokedex-"+interrupted.next.sha256()+".jar"));
        Files.writeString(marker(interrupted), "sha256="+interrupted.next.sha256()+"\nfile="+
                interruptedNew.getFileName()+"\n");
        Files.delete(file(interrupted,interrupted.old));
        denies(()->PrivateManagedUpgrade.recoverPending(interrupted.root,"hype_pokedex",()->false),
              "cannot recover while game active");
        ok(PrivateManagedUpgrade.recoverPending(interrupted.root,"hype_pokedex",()->true),
           "offline prelaunch recovery found interrupted journal");
        ok(Files.exists(file(interrupted,interrupted.old)) && !Files.exists(interruptedNew),
           "interrupted upgrade recovered old and removed new");
        ok(Files.readString(marker(interrupted)).contains(interrupted.old.sha256()),
           "recovery restored old marker");
        ok(!Files.exists(interrupted.root.resolve(".hype-private-managed/hype_pokedex.pending")),
           "recovery deleted completed pending journal");
        ok(!PrivateManagedUpgrade.recoverPending(interrupted.root,"hype_pokedex",()->true),
           "recovery is idempotent with no pending journal");
        System.out.println("PASS: "+checks+" simulated managed-upgrade assertions. No production installs.");
    }
}
