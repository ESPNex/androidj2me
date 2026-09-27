/*
 * Click nbfs://nbhost/SystemFileSystem/Templates/Licenses/license-default.txt to change this license
 * Click nbfs://nbhost/SystemFileSystem/Templates/Classes/Main.java to edit this template
 */
package android.j2me.edition;

import java.awt.Color;
import java.io.File;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.logging.Level;
import java.util.logging.Logger;
import javax.sound.sampled.AudioInputStream;
import javax.sound.sampled.AudioSystem;
import javax.sound.sampled.Clip;
import javax.sound.sampled.LineUnavailableException;
import javax.sound.sampled.UnsupportedAudioFileException;
import javax.swing.SwingUtilities;



/**
 *
 * @author Utente
 */
public class SystemManagement {

    /**
     * @param args the command line arguments
     */
    public static void main(String[] args) throws InterruptedException, LineUnavailableException, UnsupportedAudioFileException, IOException {
        
        BootAnim b = new BootAnim();
        HomeScreen h = new HomeScreen();
        GooglePlayLoginScreen login = new GooglePlayLoginScreen ();
        Settings s = new Settings();
        SimpleDateFormat formatter = new SimpleDateFormat ("HH:mm");
        Date date = new Date ();
        b.setVisible(true);
        for (int i = 0; i <= 100; i++)
        {
           b.bootanimbar.setValue(i);
           Thread.sleep(150);
           
     
        
        if (b.bootanimbar.getValue() == 100)
        {
            b.setVisible(false);
            h.setVisible(true);
            h.ShutdownScreen.setVisible(false);
            h.BatteryLowAlertScreen.setVisible(false);
            h.setSize(400,370);
            h.wifi_statusbar_icon.setVisible(false);
            s.wifi_statusbar_icon.setVisible(false);
            
            
        }
        }
        
        for (int i = 100; i >= 0; i--)
        {
            h.time.setText(formatter.format(date));
            
            h.batterybar.setValue(i);
            
            Thread.sleep(60000);
        
        if (h.batterybar.getValue() == 20)
          {
            h.BatteryLowAlertScreen.setBackground(Color.darkGray);
            h.BatteryLowAlertScreen.setVisible(true); 
            h.batterybar.setForeground(Color.RED);
            // Specify the path of the audio file
            File audioFile = new File("C:\\Users\\Utente\\Documents\\NetBeansProjects\\Android J2ME Edition\\src\\android\\j2me\\edition\\lowbattery.wav");

            // Create an AudioInputStream from the audio file
            AudioInputStream audioStream = AudioSystem.getAudioInputStream(audioFile);

            // Get a clip resource
            Clip audioClip = AudioSystem.getClip();

            // Open audio clip and load samples from the audio input stream
            audioClip.open(audioStream);
            
            // Start playing the audio
            audioClip.start();
          }
          
          if (h.batterybar.getValue() == 0)
          {
             h.BatteryLowAlertScreen.setVisible(false);
             h.ShutdownScreen.setBackground(Color.darkGray);
             h.ShutdownScreen.setVisible(true);
             Thread.sleep(7000);
             System.exit(0);
               
          }
        }
        
       }
    
    
}
        
        
    
    



         
        
        
         
          
        
        
        
          
            
    
    
    
    


