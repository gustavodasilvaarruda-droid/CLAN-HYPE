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
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Synthetic JARs only: verifies algorithm for all four restricted module IDs. */
public final class PrivateMultiModUpgradeTest {
    static int passed;
    static void yes(boolean ok, String label) {if (!ok) throw new AssertionError(label);passed++;}
    static String sha(byte[] bytes) throws Exception {
        var sb=new StringBuilder(); for(var b: MessageDigest.getInstance("SHA-256").digest(bytes))
            sb.append(String.format("%02x",b&255));return sb.toString();
    }
    static byte[] jar(String id, String version, int salt) throws Exception {
        var buffer=new ByteArrayOutputStream();
        try(var zip=new ZipOutputStream(buffer)) {
            zip.putNextEntry(new ZipEntry("fabric.mod.json"));
            zip.write(("{\"schemaVersion\":1,\"id\":\""+id+"\",\"version\":\""+version+"\"}")
                .getBytes(StandardCharsets.UTF_8));zip.closeEntry();
            zip.putNextEntry(new ZipEntry("Dummy.class"));
            byte[] payload=new byte[10000];for(int i=0;i<payload.length;i++)payload[i]=(byte)(i*97+(i>>>4)+salt);
            zip.write(payload);zip.closeEntry();
        }return buffer.toByteArray();
    }
    static PrivateModUpdater.Release signed(KeyPair kp,String id,String version,byte[] jar,int n) throws Exception {
        var hash=sha(jar);String url=PrivateModUpdater.API+"/mods/"+id+"/"+hash+".jar";
        var map=Map.of("release",String.valueOf(n),"version",version,"url",url,"sha256",hash,
                "size",String.valueOf(jar.length),"minecraft","1.21.1","mod_id",id,"channel","stable");
        var canonical=new StringBuilder();for(String f:PrivateModUpdater.FIELDS)
            canonical.append(f).append('=').append(map.get(f)).append('\n');
        Signature sig=Signature.getInstance("Ed25519");sig.initSign(kp.getPrivate());
        sig.update(canonical.toString().getBytes(StandardCharsets.US_ASCII));
        var manifest=canonical+"signature="+Base64.getEncoder().encodeToString(sig.sign())+"\n";
        return new PrivateModUpdater.Release(id,version,hash,jar.length,n,url,manifest);
    }
    public static void main(String[] args) throws Exception {
        KeyPair signer=KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        var root=Files.createTempDirectory("hype-all-four-private-mods-");
        Files.createDirectory(root.resolve("config"));
        Files.writeString(root.resolve("config/hype-bootstrap.properties"),"update_mode=after_exit\n");
        var staging=Files.createDirectory(root.resolve(".hype-private-staging"));
        List<String> ids=List.of("hype_pokedex","hype_breed_calculator","hype_battlefield","hype_battle_ai");
        for(int i=0;i<ids.size();i++) {
            String id=ids.get(i);
            byte[] oldJar=jar(id,"1.0.0-test",i),newJar=jar(id,"2.0.0-test",i+10);
            var oldRelease=signed(signer,id,"1.0.0-test",oldJar,1);
            var newRelease=signed(signer,id,"2.0.0-test",newJar,2);
            Files.write(staging.resolve(id+"-"+oldRelease.sha256()+".jar"),oldJar);
            Files.write(staging.resolve(id+"-"+newRelease.sha256()+".jar"),newJar);
            yes(PrivateFirstInstallTransaction.apply(root,oldRelease,signer.getPublic(),
                ()->true,()->true,()->{}) == PrivateFirstInstallTransaction.Outcome.INSTALLED,
                "first install of "+id);
            yes(PrivateManagedUpgrade.upgrade(root,newRelease,signer.getPublic(),
                ()->true,()->true,()->{}) == PrivateManagedUpgrade.Outcome.UPDATED,
                "upgrade of "+id);
            yes(Files.exists(root.resolve("mods/hype-"+id+"-"+newRelease.sha256()+".jar")),
                "correct installed JAR for "+id);
            yes(!Files.exists(root.resolve("mods/hype-"+id+"-"+oldRelease.sha256()+".jar")),
                "old version removed for "+id);
            yes(Files.exists(root.resolve(".hype-private-backups/hype-"+id+"-"+oldRelease.sha256()+".jar")),
                "backup retained for "+id);
            yes(Files.readString(root.resolve(".hype-private-managed/"+id+".state")).contains(newRelease.sha256()),
                "ownership marker correct for "+id);
        }
        try(var scan=Files.newDirectoryStream(root.resolve("mods"),"*.jar")) {
            int count=0;for(Path ignored:scan)count++;
            yes(count==4,"exactly four private mods installed with no duplicate IDs");
        }
        System.out.println("PASS: "+passed+" 4-mod synthetic upgrade checks (offline; not real mod builds)");
    }
}
